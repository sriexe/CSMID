"""
src/neural_forecaster.py — Neural Time-Series Forecaster for CSMID

Improved TCN + DilatedGRU + Soft Focus Mechanism, adapted for CS2 skin
price prediction. Designed as a drop-in replacement for BaselineForecaster
in the existing CSMID prediction pipeline.

Architecture improvements over the original (pasted_content.txt):
  1. Hard binary mask → Soft Gumbel-sigmoid gate (stable gradients)
  2. Dead feedforward layer → Active bridge between TCN and GRU
  3. Fixed dropout=0.5 → Adaptive pre-activation dropout
  4. Ambiguous OUTPUT_DIM=10 → Multi-horizon head with per-step confidence
  5. No input normalization → Learned normalization + positional encoding
  6. Hardcoded TCN channels → Configurable from constructor

Integration:
  - NeuralForecaster class exposes .forecast(features) → same contract as
    BaselineForecaster, so it slots into generate_forecasts() and backtest
  - DataAdapter converts Supabase price records → tensors
  - Training loop supports walk-forward incremental training
  - Model checkpoints saved to data/models/
"""

import logging
import math
import os
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path

from src.config import PROJECT_ROOT
from src.forecaster import ForecastConfig, PriceFeatureExtractor

logger = logging.getLogger("CSMID.neural_forecaster")

# Default model storage directory
MODEL_DIR = PROJECT_ROOT / "data" / "models"


# =====================================================================
# 1. THE IMPROVED MODEL (architecture from improved_model.py)
# =====================================================================

class SoftFocusGate(nn.Module):
    """
    Soft gated temporal attention with Gumbel-sigmoid for stable training.
    Learns which timesteps are relevant via cosine + dot-product similarity.
    """

    def __init__(self, proj_dim: int, alpha: float = 0.5, beta: float = 0.5,
                 theta: float = 0.5, temperature: float = 2.0):
        super().__init__()
        self.alpha = alpha
        self.beta = beta
        self.theta = theta
        self.temperature = nn.Parameter(torch.tensor(temperature))
        self.projection = nn.Linear(proj_dim, proj_dim)
        self.bias = nn.Parameter(torch.zeros(proj_dim))

    def set_temperature(self, temp: float):
        with torch.no_grad():
            self.temperature.fill_(max(temp, 0.1))

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Returns:
            x_filtered: [B, T, D] — gated features
            gate_scores: [B, T] — raw relevance scores (for interpretability)
        """
        batch_size, seq_len, proj_dim = x.size()
        p = self.projection(x) + self.bias

        p_normalized = F.normalize(p, p=2, dim=2)
        C = torch.matmul(p_normalized, p_normalized.transpose(1, 2))
        D = torch.matmul(p, p.transpose(1, 2))
        A = self.alpha * C + self.beta * D

        max_scores, _ = torch.max(A, dim=2)  # [B, T]

        if self.training:
            u = torch.rand_like(max_scores).clamp(min=1e-10, max=1.0 - 1e-10)
            gumbel_noise = -torch.log(-torch.log(u))
            logits = max_scores - self.theta
            soft_gate = torch.sigmoid((logits + gumbel_noise) / self.temperature)
        else:
            soft_gate = torch.sigmoid((max_scores - self.theta) / self.temperature)

        gate = soft_gate.unsqueeze(2).expand_as(x)
        x_filtered = 0.1 * x + 0.9 * (x * gate)

        return x_filtered, max_scores


class AdaptiveResidualBlock(nn.Module):
    """
    Pre-activation residual block with depth-adaptive dropout.
    Deeper layers get more regularization; early layers preserve signal.
    """

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int,
                 stride: int, dilation: int, depth_index: int = 0,
                 total_depth: int = 4, base_dropout: float = 0.2):
        super().__init__()
        self.dropout_rate = base_dropout + 0.05 * depth_index / max(total_depth - 1, 1)
        self.dropout_rate = min(self.dropout_rate, 0.4)

        self.bn1 = nn.BatchNorm1d(in_channels)
        self.conv1 = nn.Conv1d(in_channels, out_channels, kernel_size=1)
        self.conv2 = nn.Conv1d(out_channels, out_channels,
                               kernel_size=kernel_size, stride=stride,
                               padding=dilation, dilation=dilation)
        self.bn2 = nn.BatchNorm1d(out_channels)
        self.conv3 = nn.Conv1d(out_channels, out_channels, kernel_size=1)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(self.dropout_rate)

        self.shortcut = nn.Conv1d(in_channels, out_channels,
                                  kernel_size=1) if in_channels != out_channels else None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.bn1(x)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.conv1(out)

        out = self.bn2(out)
        out = self.relu(out)
        out = self.dropout(out)
        out = self.conv2(out)
        out = self.conv3(out)

        res = x if self.shortcut is None else self.shortcut(x)
        if x.size(2) != res.size(2):
            res = F.pad(res, (0, x.size(2) - res.size(2)))
        return out + res


class NeuralTCNEncoder(nn.Module):
    """Configurable dilated causal convolution encoder."""

    def __init__(self, num_inputs: int, num_channels: List[int],
                 kernel_size: int = 3, base_dropout: float = 0.2):
        super().__init__()
        layers = []
        for i, out_ch in enumerate(num_channels):
            dilation_size = 2 ** i
            in_ch = num_inputs if i == 0 else num_channels[i - 1]
            layers.append(AdaptiveResidualBlock(
                in_ch, out_ch, kernel_size, stride=1,
                dilation=dilation_size, depth_index=i,
                total_depth=len(num_channels), base_dropout=base_dropout,
            ))
        self.network = nn.Sequential(*layers)
        self.num_channels = num_channels
        self.receptive_field = 1 + sum((kernel_size - 1) * (2 ** i) for i in range(len(num_channels)))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)


class DilatedGRUDecoder(nn.Module):
    """
    2-layer GRU where layer 0 processes every timestep and
    layer 1 processes every d-th timestep (dilated recurrence).
    """

    def __init__(self, input_size: int, hidden_size: int,
                 num_layers: int = 2, dilation: int = 2):
        super().__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dilation = dilation
        self.gru_cells = nn.ModuleList([
            nn.GRUCell(input_size if i == 0 else hidden_size, hidden_size)
            for i in range(num_layers)
        ])

    def forward(self, x: torch.Tensor, h: List[torch.Tensor]):
        seq_len, batch_size, _ = x.size()
        outputs = []
        for t in range(seq_len):
            for i, gru_cell in enumerate(self.gru_cells):
                if i == 0:
                    h[i] = gru_cell(x[t], h[i])
                elif t % self.dilation == 0:
                    h[i] = gru_cell(h[i - 1], h[i])
            outputs.append(h[-1])
        return torch.stack(outputs), h

    def init_hidden(self, batch_size: int, device: torch.device):
        return [torch.zeros(batch_size, self.hidden_size, device=device)
                for _ in range(self.num_layers)]


class TemporalPositionalEncoding(nn.Module):
    """Learned positional + interval encoding for irregular time series."""

    def __init__(self, d_model: int, max_seq_len: int = 500):
        super().__init__()
        self.encoding = nn.Parameter(torch.randn(1, max_seq_len, d_model) * 0.02)
        self.interval_encoding = nn.Linear(1, d_model)

    def forward(self, x: torch.Tensor, time_intervals: Optional[torch.Tensor] = None) -> torch.Tensor:
        seq_len = x.size(1)
        pos_encoding = self.encoding[:, :seq_len, :]
        x = x + pos_encoding
        if time_intervals is not None:
            interval_feat = self.interval_encoding(time_intervals.unsqueeze(-1))
            x = x + interval_feat
        return x


class MultiHorizonHead(nn.Module):
    """Per-horizon prediction heads sharing a common backbone."""

    def __init__(self, hidden_dim: int, horizons: List[int], output_features: int = 3):
        super().__init__()
        self.horizons = horizons
        self.output_features = output_features
        self.shared = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
        )
        self.horizon_heads = nn.ModuleList([
            nn.Linear(hidden_dim, output_features) for _ in horizons
        ])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        base = self.shared(x)
        return torch.stack([head(base) for head in self.horizon_heads], dim=1)


# =====================================================================
# 2. THE FULL NEURAL MODEL
# =====================================================================

class NeuralPriceForecaster(nn.Module):
    """
    Full improved architecture:
      LayerNorm → PositionalEncoding → Projection → SoftFocusGate
      → TCN Encoder → Feedforward Bridge → DilatedGRU → Skip + Pool
      → MultiHorizonHead
    """

    def __init__(
        self,
        input_dim: int = 12,
        proj_dim: int = 64,
        ff_dim: int = 128,
        tcn_channels: Optional[List[int]] = None,
        kernel_size: int = 3,
        gru_hidden: int = 128,
        gru_layers: int = 2,
        gru_dilation: int = 2,
        output_horizons: Optional[List[int]] = None,
        alpha: float = 0.5,
        beta: float = 0.5,
        theta: float = 0.5,
        temperature: float = 2.0,
        enc_dropout: float = 0.2,
        max_seq_len: int = 500,
    ):
        super().__init__()
        self.input_dim = input_dim
        self.proj_dim = proj_dim
        self.ff_dim = ff_dim

        if tcn_channels is None:
            tcn_channels = [64, 64, 128]
        if output_horizons is None:
            output_horizons = [1, 3, 6, 12, 24, 48, 72, 168]

        self.input_norm = nn.LayerNorm(input_dim)
        self.positional_encoding = TemporalPositionalEncoding(proj_dim, max_seq_len)
        self.projection_layer = nn.Conv1d(input_dim, proj_dim, kernel_size=1)
        self.focus_mechanism = SoftFocusGate(
            proj_dim, alpha=alpha, beta=beta, theta=theta, temperature=temperature
        )
        self.tcn_encoder = NeuralTCNEncoder(
            proj_dim, tcn_channels, kernel_size=kernel_size, base_dropout=enc_dropout
        )

        last_tcn_channel = tcn_channels[-1]
        self.feedforward = nn.Linear(last_tcn_channel, ff_dim)
        self.gru_decoder = DilatedGRUDecoder(ff_dim, gru_hidden, gru_layers, gru_dilation)
        self.skip_proj = nn.Linear(last_tcn_channel, gru_hidden)
        self.output_head = MultiHorizonHead(gru_hidden, output_horizons)

        self.tcn_channels = tcn_channels
        self.output_horizons = output_horizons

    def forward(self, x: torch.Tensor,
                time_intervals: Optional[torch.Tensor] = None
                ) -> Tuple[torch.Tensor, torch.Tensor]:
        x = self.input_norm(x)

        # Project first, then add positional encoding
        x = x.permute(0, 2, 1)
        x = self.projection_layer(x)
        x = x.permute(0, 2, 1)
        x = self.positional_encoding(x, time_intervals)

        # Focus gate
        x_filtered, gate_scores = self.focus_mechanism(x)

        # TCN encoder
        x_tcn = x_filtered.permute(0, 2, 1)
        tcn_out = self.tcn_encoder(x_tcn).permute(0, 2, 1)

        # Feedforward bridge
        ff_out = self.feedforward(tcn_out)

        # GRU
        tcn_for_gru = ff_out.permute(1, 0, 2)
        h = self.gru_decoder.init_hidden(tcn_for_gru.size(1), tcn_for_gru.device)
        gru_out, _ = self.gru_decoder(tcn_for_gru, h)
        gru_out = gru_out.permute(1, 2, 0)

        # Skip + pool
        combined = gru_out + self.skip_proj(tcn_out).permute(0, 2, 1)
        pooled = F.adaptive_avg_pool1d(combined, 1).squeeze(2)

        # Multi-horizon predictions
        predictions = self.output_head(pooled)

        return predictions, gate_scores


# =====================================================================
# 3. DATA ADAPTER — Supabase records → tensors
# =====================================================================

# Feature columns used for the neural model (12-dim vector per timestep)
FEATURE_COLUMNS = [
    "lowest_price", "median_price", "volume",
    "price_pct_change", "price_rolling_mean", "price_rolling_std",
    "price_momentum", "price_cv", "volume_rolling_mean",
    "hours_since_last", "day_of_week_sin", "day_of_week_cos",
]

INPUT_DIM = len(FEATURE_COLUMNS)  # 12


class NeuralDataAdapter:
    """
    Converts Supabase price history records into tensors suitable for
    the neural forecaster. Handles normalization, padding, and irregular
    time intervals.
    """

    def __init__(self, max_seq_len: int = 50):
        self.max_seq_len = max_seq_len
        self._fitted = False
        self._means = np.zeros(INPUT_DIM)
        self._stds = np.ones(INPUT_DIM)

    def records_to_features(self, records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Convert raw price records into a feature dict ready for tensor conversion.

        Returns None if insufficient data.
        """
        extractor = PriceFeatureExtractor()
        df = extractor.records_to_dataframe(records)
        if len(df) < 10:
            return None

        # Compute engineered features
        prices = df["price"].values.astype(float)

        # Rolling statistics
        df["price_pct_change"] = df["price"].pct_change().fillna(0)
        df["price_rolling_mean"] = df["price"].rolling(5, min_periods=1).mean()
        df["price_rolling_std"] = df["price"].rolling(5, min_periods=1).std().fillna(0)

        # Momentum (3-step % change)
        df["price_momentum"] = 0.0
        if len(df) >= 3:
            df["price_momentum"] = (df["price"] - df["price"].shift(3)) / df["price"].shift(3)
            df["price_momentum"] = df["price_momentum"].fillna(0)

        # Coefficient of variation (rolling 5)
        df["price_cv"] = df["price_rolling_std"] / df["price_rolling_mean"].replace(0, np.nan)
        df["price_cv"] = df["price_cv"].fillna(0)

        # Volume rolling mean
        if "volume" in df.columns:
            df["volume_rolling_mean"] = df["volume"].rolling(5, min_periods=1).mean()
        else:
            df["volume"] = 0
            df["volume_rolling_mean"] = 0

        # Hours since last observation
        df["hours_since_last"] = 0.0
        if len(df) >= 2:
            df["hours_since_last"] = df["scraped_at"].diff().dt.total_seconds() / 3600.0
        df["hours_since_last"] = df["hours_since_last"].fillna(0).clip(upper=168)

        # Day-of-week encoding (cyclic)
        dow = df["scraped_at"].dt.dayofweek.astype(float)
        df["day_of_week_sin"] = np.sin(2 * np.pi * dow / 7)
        df["day_of_week_cos"] = np.cos(2 * np.pi * dow / 7)

        # Extract feature matrix
        feature_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
        feature_matrix = df[feature_cols].values.astype(float)

        # Handle NaN/Inf
        feature_matrix = np.nan_to_num(feature_matrix, nan=0.0, posinf=0.0, neginf=0.0)

        # Time intervals for positional encoding
        intervals = df["hours_since_last"].values.astype(float)

        # Target: next price (for training)
        target_prices = df["price"].values[1:]
        current_prices = df["price"].values[:-1]

        return {
            "feature_matrix": feature_matrix,
            "intervals": intervals,
            "target_prices": target_prices,
            "current_prices": current_prices,
            "n_points": len(df),
            "skin_name": records[0].get("skin_name", "unknown"),
            "timestamps": df["scraped_at"].values,
        }

    def fit_scaler(self, features_list: List[Dict[str, Any]]):
        """Fit normalization scalers across all skins."""
        all_features = []
        for f in features_list:
            if f is not None:
                all_features.append(f["feature_matrix"])
        if not all_features:
            return

        combined = np.vstack(all_features)
        self._means = combined.mean(axis=0)
        self._stds = combined.std(axis=0)
        self._stds[self._stds == 0] = 1.0  # Avoid division by zero
        self._fitted = True
        logger.info("Scaler fitted: %d samples across %d skins", len(combined), len(features_list))

    def normalize(self, features: np.ndarray) -> np.ndarray:
        """Apply fitted normalization."""
        if not self._fitted:
            return features
        return (features - self._means) / self._stds

    def features_to_tensor(self, features_dict: Dict[str, Any]) -> Optional[Dict[str, torch.Tensor]]:
        """
        Convert a single skin's features dict into tensors for the model.

        Returns dict with 'input', 'time_intervals', 'target', or None if too short.
        """
        raw = features_dict["feature_matrix"]
        n = len(raw)

        if n < 10:
            return None

        # Take last max_seq_len timesteps
        if n > self.max_seq_len:
            raw = raw[-self.max_seq_len:]
            intervals = features_dict["intervals"][-self.max_seq_len:]
            targets = features_dict["target_prices"][-self.max_seq_len:]
            currents = features_dict["current_prices"][-self.max_seq_len:]
        else:
            intervals = features_dict["intervals"]
            targets = features_dict["target_prices"]
            currents = features_dict["current_prices"]

        # Pad to max_seq_len if needed
        pad_len = self.max_seq_len - len(raw)
        if pad_len > 0:
            raw = np.pad(raw, ((pad_len, 0), (0, 0)), mode="constant")
            intervals = np.pad(intervals, (pad_len, 0), mode="constant")
            targets = np.pad(targets, (pad_len, 0), mode="constant")
            currents = np.pad(currents, (pad_len, 0), mode="constant")

        norm_features = self.normalize(raw)

        return {
            "input": torch.tensor(norm_features, dtype=torch.float32).unsqueeze(0),  # [1, T, D]
            "time_intervals": torch.tensor(intervals, dtype=torch.float32).unsqueeze(0),  # [1, T]
            "target": torch.tensor(targets, dtype=torch.float32).unsqueeze(0),  # [1, T]
            "current": torch.tensor(currents, dtype=torch.float32).unsqueeze(0),  # [1, T]
        }

    def build_dataset(
        self,
        records_by_skin: Dict[str, List[Dict[str, Any]]],
    ) -> Tuple[Dict[str, torch.Tensor], Dict[str, Dict[str, Any]]]:
        """
        Build training tensors for all skins.

        Returns:
            tensors: {"inputs": [N, T, D], "intervals": [N, T], "targets": [N, T]}
            metadata: per-skin feature info for reporting
        """
        # Phase 1: extract features per skin
        features_by_skin = {}
        for skin_name, records in records_by_skin.items():
            feat = self.records_to_features(records)
            if feat is not None:
                features_by_skin[skin_name] = feat

        if not features_by_skin:
            return {}, {}

        # Phase 2: fit scaler
        self.fit_scaler(list(features_by_skin.values()))

        # Phase 3: convert to tensors
        inputs = []
        intervals = []
        targets = []

        for skin_name, feat in features_by_skin.items():
            tensor_dict = self.features_to_tensor(feat)
            if tensor_dict is not None:
                inputs.append(tensor_dict["input"])
                intervals.append(tensor_dict["time_intervals"])
                targets.append(tensor_dict["target"])

        if not inputs:
            return {}, {}

        return {
            "inputs": torch.cat(inputs, dim=0),
            "intervals": torch.cat(intervals, dim=0),
            "targets": torch.cat(targets, dim=0),
        }, features_by_skin


# =====================================================================
# 4. TRAINING LOOP
# =====================================================================

class NeuralTrainer:
    """
    Walk-forward compatible training loop.
    - Loss: MSE on price prediction at the nearest horizon (12h)
    - Temperature annealing for the focus gate
    - Checkpoint saving to data/models/
    """

    def __init__(
        self,
        model: NeuralPriceForecaster,
        learning_rate: float = 1e-3,
        weight_decay: float = 1e-4,
        epochs: int = 50,
        batch_size: int = 16,
        horizon_index: int = 3,  # Index of 12h horizon in output_horizons
        checkpoint_path: Optional[str] = None,
    ):
        self.model = model
        self.lr = learning_rate
        self.weight_decay = weight_decay
        self.epochs = epochs
        self.batch_size = batch_size
        self.horizon_index = horizon_index  # output[:, horizon_index, 0] = price pred
        self.checkpoint_path = checkpoint_path or str(MODEL_DIR / "neural_forecaster.pt")

        self.optimizer = torch.optim.AdamW(
            model.parameters(), lr=learning_rate, weight_decay=weight_decay
        )
        self.loss_fn = nn.MSELoss()

        # Temperature annealing: start soft (explore), end sharp (exploit)
        self.initial_temp = 5.0
        self.final_temp = 0.5

    def _anneal_temperature(self, epoch: int):
        """Linear temperature decay over training."""
        progress = epoch / max(self.epochs - 1, 1)
        temp = self.initial_temp + (self.final_temp - self.initial_temp) * progress
        self.model.focus_mechanism.set_temperature(temp)

    def train(
        self,
        tensors: Dict[str, torch.Tensor],
        features_by_skin: Dict[str, Dict[str, Any]],
        val_split: float = 0.2,
    ) -> Dict[str, Any]:
        """
        Train the model on the provided tensors.

        Returns training metrics dict.
        """
        device = next(self.model.parameters()).device
        inputs = tensors["inputs"].to(device)
        intervals = tensors["intervals"].to(device)
        targets = tensors["targets"].to(device)

        n_samples = inputs.size(0)
        val_size = max(int(n_samples * val_split), 1)
        train_size = n_samples - val_size

        # Split (no shuffle — walk-forward style, last val_split is validation)
        train_inputs = inputs[:train_size]
        train_intervals = intervals[:train_size]
        train_targets = targets[:train_size]

        val_inputs = inputs[train_size:]
        val_intervals = intervals[train_size:]
        val_targets = targets[train_size:]

        history = {"train_loss": [], "val_loss": [], "temperature": []}

        for epoch in range(self.epochs):
            # Anneal temperature
            self._anneal_temperature(epoch)
            self.model.train()

            # Mini-batch training
            epoch_loss = 0.0
            n_batches = 0

            indices = torch.randperm(train_size, device=device)
            for start in range(0, train_size, self.batch_size):
                end = min(start + self.batch_size, train_size)
                idx = indices[start:end]

                x = train_inputs[idx]
                ti = train_intervals[idx]
                y_true = train_targets[idx]

                # Forward
                preds, _ = self.model(x, ti)
                # Predict price at the chosen horizon
                y_pred = preds[:, self.horizon_index, 0]  # [B]
                # Target: price at the same horizon step
                y_target = y_true[:, -1]  # Last timestep = current → predict next
                loss = self.loss_fn(y_pred, y_target)

                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
                self.optimizer.step()

                epoch_loss += loss.item()
                n_batches += 1

            # Validation
            self.model.eval()
            with torch.no_grad():
                val_preds, _ = self.model(val_inputs, val_intervals)
                val_y_pred = val_preds[:, self.horizon_index, 0]
                val_y_true = val_targets[:, -1]
                val_loss = self.loss_fn(val_y_pred, val_y_true).item()

            train_loss = epoch_loss / max(n_batches, 1)
            history["train_loss"].append(train_loss)
            history["val_loss"].append(val_loss)
            history["temperature"].append(
                self.model.focus_mechanism.temperature.item()
            )

            if (epoch + 1) % 10 == 0 or epoch == 0:
                logger.info(
                    "Epoch %3d/%d | train_loss=%.4f | val_loss=%.4f | temp=%.2f",
                    epoch + 1, self.epochs, train_loss, val_loss,
                    self.model.focus_mechanism.temperature.item(),
                )

        # Save checkpoint
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        torch.save({
            "model_state_dict": self.model.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "epoch": self.epochs,
            "train_loss": history["train_loss"][-1],
            "val_loss": history["val_loss"][-1],
        }, self.checkpoint_path)
        logger.info("Model checkpoint saved to: %s", self.checkpoint_path)

        return history

    @classmethod
    def load_checkpoint(cls, checkpoint_path: Optional[str] = None) -> Optional["NeuralTrainer"]:
        """Load a trained model from checkpoint. Returns None if no checkpoint exists."""
        path = checkpoint_path or str(MODEL_DIR / "neural_forecaster.pt")
        if not os.path.exists(path):
            return None

        device = torch.device("cpu")
        checkpoint = torch.load(path, map_location=device, weights_only=True)

        model = NeuralPriceForecaster()
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()

        trainer = cls(model)
        trainer.model = model
        return trainer


# =====================================================================
# 5. CSMID-COMPATIBLE WRAPPER — Drop-in for BaselineForecaster
# =====================================================================

class NeuralForecasterWrapper:
    """
    Exposes the same .forecast(features) interface as BaselineForecaster.
    Falls back to BaselineForecaster if the neural model hasn't been trained yet
    or if the skin has insufficient data.

    Usage:
        wrapper = NeuralForecasterWrapper(min_data_points=30)
        result = wrapper.forecast(features)  # same dict as BaselineForecaster
    """

    def __init__(
        self,
        config: Optional[ForecastConfig] = None,
        checkpoint_path: Optional[str] = None,
    ):
        self.config = config or ForecastConfig()
        self.min_data_points = max(self.config.MIN_DATA_POINTS, 30)  # Neural needs more data

        # Load trained model if available
        trainer = NeuralTrainer.load_checkpoint(checkpoint_path)
        if trainer is not None:
            self.model = trainer.model
            self._has_model = True
            logger.info("Neural forecaster loaded from checkpoint")
        else:
            self.model = None
            self._has_model = False
            logger.info("No neural checkpoint found — will use baseline fallback")

        self.adapter = NeuralDataAdapter()
        self._baseline = None  # Lazy-loaded

    @property
    def baseline(self):
        """Lazy-load the baseline forecaster for fallback."""
        if self._baseline is None:
            from src.forecaster import BaselineForecaster
            self._baseline = BaselineForecaster(self.config)
        return self._baseline

    def can_forecast(self, features: Dict[str, Any]) -> bool:
        if not features:
            return False
        return features.get("n_points", 0) >= self.min_data_points

    def forecast(self, features: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Same interface as BaselineForecaster.forecast().
        Returns None if insufficient data.
        """
        if not self.can_forecast(features):
            return None

        # If neural model is trained, use it
        if self._has_model and self.model is not None:
            return self._neural_forecast(features)

        # Otherwise fall back to baseline
        return self.baseline.forecast(features)

    def _neural_forecast(self, features: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Run a single-skin forecast through the neural model."""
        try:
            # We need raw records to build the tensor — reconstruct from features
            # This is a simplified path; for full training data we'd use the adapter
            current = features["current_price"]
            cv = features["cv"]
            slope = features["slope"]
            momentum = features["momentum"]

            # Construct a minimal feature vector from available features
            # In production, this would come from the full adapter pipeline
            feature_vec = np.zeros((1, 1, INPUT_DIM))
            feature_vec[0, 0, 0] = current  # lowest_price proxy
            feature_vec[0, 0, 1] = features.get("median_price", current)
            feature_vec[0, 0, 2] = 0.0  # volume (not in features dict)
            feature_vec[0, 0, 3] = features.get("momentum", 0.0)
            feature_vec[0, 0, 4] = features.get("mean_price", current)
            feature_vec[0, 0, 5] = features.get("std_price", 0.0)
            feature_vec[0, 0, 6] = momentum
            feature_vec[0, 0, 7] = cv
            feature_vec[0, 0, 8] = 0.0  # volume_rolling_mean
            feature_vec[0, 0, 9] = features.get("avg_interval_hours", 12.0)
            feature_vec[0, 0, 10] = 0.0  # day_of_week_sin
            feature_vec[0, 0, 11] = 1.0  # day_of_week_cos

            # Normalize
            norm_vec = self.adapter.normalize(feature_vec[0, 0, :])
            x = torch.tensor(norm_vec, dtype=torch.float32).unsqueeze(0).unsqueeze(0)
            x = x.expand(1, 50, INPUT_DIM)  # Pad to 50 timesteps
            x[:, :1, :] = torch.tensor(norm_vec, dtype=torch.float32)

            intervals = torch.zeros(1, 50)
            intervals[:, 0] = features.get("avg_interval_hours", 12.0)

            self.model.eval()
            with torch.no_grad():
                preds, gate_scores = self.model(x, intervals)

            # Extract 12h forecast (index 3)
            idx_12h = 3  # horizons = [1, 3, 6, 12, ...]
            pred_raw = preds[0, idx_12h, 0].item()
            confidence_raw = torch.sigmoid(preds[0, idx_12h, 1]).item()

            # Denormalize: the model predicts in normalized space
            # For a simple approach, scale back using current price
            predicted = max(current * (1 + pred_raw), 0.01)

            pct_change = (predicted - current) / current if current > 0 else 0.0

            if pct_change > 0.02:
                direction = "UP"
            elif pct_change < -0.02:
                direction = "DOWN"
            else:
                direction = "FLAT"

            confidence = float(min(max(confidence_raw, 0.0), 1.0))

            return {
                "predicted_price": round(float(predicted), 4),
                "direction": direction,
                "confidence": round(confidence, 3),
                "pct_change": round(float(pct_change * 100), 2),
                "horizon_hours": 12,
                "components": {
                    "model": "neural_tcn_gru",
                    "gate_scores_top": gate_scores[0, :5].tolist(),
                },
                "features": features,
            }

        except Exception as exc:
            logger.warning("Neural forecast failed for features, falling back to baseline: %s", exc)
            return self.baseline.forecast(features)


# =====================================================================
# 6. TRAINING PIPELINE — Trains the neural model on all skins
# =====================================================================

def train_neural_model(
    records_by_skin: Dict[str, List[Dict[str, Any]]],
    epochs: int = 50,
    learning_rate: float = 1e-3,
    checkpoint_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full training pipeline:
    1. Extract features from all skins
    2. Build tensors via NeuralDataAdapter
    3. Train NeuralPriceForecaster
    4. Save checkpoint

    Returns training history.
    """
    if len(records_by_skin) < 5:
        logger.warning("Need at least 5 skins with data for training. Got %d.", len(records_by_skin))
        return {"status": "skipped", "reason": "insufficient_skins"}

    # Build dataset
    adapter = NeuralDataAdapter()
    tensors, features_by_skin = adapter.build_dataset(records_by_skin)

    if not tensors:
        logger.warning("No usable training data after feature extraction.")
        return {"status": "skipped", "reason": "no_training_data"}

    n_skins = tensors["inputs"].size(0)
    logger.info("Training on %d skins, input shape: %s", n_skins, str(tensors["inputs"].shape))

    # Create model
    model = NeuralPriceForecaster(input_dim=INPUT_DIM)
    logger.info(
        "Model params: %.1fK | TCN channels: %s | Horizons: %s",
        sum(p.numel() for p in model.parameters()) / 1000,
        model.tcn_channels,
        model.output_horizons,
    )

    # Train
    trainer = NeuralTrainer(
        model,
        learning_rate=learning_rate,
        epochs=epochs,
        checkpoint_path=checkpoint_path,
    )
    history = trainer.train(tensors, features_by_skin)

    return {
        "status": "trained",
        "n_skins": n_skins,
        "final_train_loss": history["train_loss"][-1],
        "final_val_loss": history["val_loss"][-1],
        "epochs": epochs,
    }
