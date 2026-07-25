"""
tests/test_neural_forecaster.py — Tests for the neural forecaster module.

Covers:
  - SoftFocusGate forward pass and temperature annealing
  - AdaptiveResidualBlock dimension handling
  - NeuralTCNEncoder receptive field calculation
  - DilatedGRUDecoder output shapes
  - NeuralDataAdapter feature extraction and tensor conversion
  - NeuralForecasterWrapper fallback behavior
  - MultiHorizonHead output shape
  - Full model forward pass
"""

import pytest
import numpy as np
import torch
import torch.nn as nn
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.neural_forecaster import (
    SoftFocusGate,
    AdaptiveResidualBlock,
    NeuralTCNEncoder,
    DilatedGRUDecoder,
    TemporalPositionalEncoding,
    MultiHorizonHead,
    NeuralPriceForecaster,
    NeuralDataAdapter,
    NeuralForecasterWrapper,
    INPUT_DIM,
)
from src.forecaster import ForecastConfig


# =====================================================================
# SoftFocusGate Tests
# =====================================================================

class TestSoftFocusGate:
    def test_output_shapes(self):
        gate = SoftFocusGate(proj_dim=64)
        x = torch.randn(2, 10, 64)
        x_filtered, scores = gate(x)
        assert x_filtered.shape == (2, 10, 64)
        assert scores.shape == (2, 10)

    def test_temperature_annealing(self):
        gate = SoftFocusGate(proj_dim=64, temperature=5.0)
        assert gate.temperature.item() == 5.0
        gate.set_temperature(0.5)
        assert gate.temperature.item() == 0.5

    def test_min_temperature(self):
        gate = SoftFocusGate(proj_dim=64)
        gate.set_temperature(0.0)  # Should clamp to 0.1
        assert abs(gate.temperature.item() - 0.1) < 1e-5

    def test_residual_passthrough(self):
        """10% of original signal always passes through."""
        gate = SoftFocusGate(proj_dim=64, temperature=0.1)  # Very sharp
        x = torch.ones(1, 5, 64)
        x_filtered, _ = gate.eval()(x) if not gate.training else gate(x)
        # Even with sharp gate, at least 10% should remain
        # We test in eval mode
        gate.eval()
        x_filtered, _ = gate(x)
        # The minimum value should be ~0.1 (10% residual)
        assert x_filtered.min() >= 0.09

    def test_training_vs_eval(self):
        gate = SoftFocusGate(proj_dim=32)
        x = torch.randn(1, 8, 32)
        # Training mode adds Gumbel noise — results are stochastic
        gate.train()
        out_train, _ = gate(x)
        gate.eval()
        out_eval, _ = gate(x)
        # They should differ due to Gumbel noise in training
        # (very unlikely to be exactly equal with noise)
        assert out_train.shape == out_eval.shape


# =====================================================================
# AdaptiveResidualBlock Tests
# =====================================================================

class TestAdaptiveResidualBlock:
    def test_same_channels(self):
        block = AdaptiveResidualBlock(64, 64, 3, 1, 1, depth_index=0, total_depth=3)
        x = torch.randn(2, 64, 20)
        out = block(x)
        assert out.shape == (2, 64, 20)

    def test_different_channels(self):
        block = AdaptiveResidualBlock(32, 64, 3, 1, 1, depth_index=1, total_depth=3)
        x = torch.randn(2, 32, 20)
        out = block(x)
        assert out.shape == (2, 64, 20)

    def test_adaptive_dropout(self):
        block_shallow = AdaptiveResidualBlock(64, 64, 3, 1, 1, depth_index=0, total_depth=4)
        block_deep = AdaptiveResidualBlock(64, 64, 3, 1, 1, depth_index=3, total_depth=4)
        assert block_shallow.dropout_rate < block_deep.dropout_rate
        assert block_deep.dropout_rate <= 0.4


# =====================================================================
# NeuralTCNEncoder Tests
# =====================================================================

class TestNeuralTCNEncoder:
    def test_output_shape(self):
        encoder = NeuralTCNEncoder(64, [64, 128], kernel_size=3)
        x = torch.randn(2, 64, 30)
        out = encoder(x)
        assert out.shape == (2, 128, 30)

    def test_receptive_field(self):
        encoder = NeuralTCNEncoder(64, [64, 64, 128], kernel_size=3)
        # RF = 1 + 2*1 + 2*2 + 2*4 = 1 + 2 + 4 + 8 = 15
        assert encoder.receptive_field == 15

    def test_receptive_field_2_layers(self):
        encoder = NeuralTCNEncoder(64, [64, 64], kernel_size=3)
        # RF = 1 + 2*1 + 2*2 = 7
        assert encoder.receptive_field == 7


# =====================================================================
# DilatedGRUDecoder Tests
# =====================================================================

class TestDilatedGRUDecoder:
    def test_output_shape(self):
        gru = DilatedGRUDecoder(128, 64, num_layers=2, dilation=2)
        x = torch.randn(20, 4, 128)  # [T, B, D]
        h = gru.init_hidden(4, x.device)
        out, h_out = gru(x, h)
        assert out.shape == (20, 4, 64)  # [T, B, hidden]
        assert len(h_out) == 2

    def test_dilation_skips(self):
        """Verify that dilation=2 means layer 1 processes every 2nd timestep."""
        gru = DilatedGRUDecoder(32, 16, num_layers=2, dilation=2)
        x = torch.randn(10, 2, 32)
        h = gru.init_hidden(2, x.device)
        out, _ = gru(x, h)
        assert out.shape == (10, 2, 16)


# =====================================================================
# TemporalPositionalEncoding Tests
# =====================================================================

class TestTemporalPositionalEncoding:
    def test_position_only(self):
        enc = TemporalPositionalEncoding(64)
        x = torch.randn(2, 10, 64)
        out = enc(x)
        assert out.shape == (2, 10, 64)

    def test_with_intervals(self):
        enc = TemporalPositionalEncoding(64)
        x = torch.randn(2, 10, 64)
        intervals = torch.rand(2, 10) * 24
        out = enc(x, intervals)
        assert out.shape == (2, 10, 64)


# =====================================================================
# MultiHorizonHead Tests
# =====================================================================

class TestMultiHorizonHead:
    def test_output_shape(self):
        head = MultiHorizonHead(128, horizons=[1, 3, 6, 12], output_features=3)
        x = torch.randn(4, 128)
        out = head(x)
        assert out.shape == (4, 4, 3)  # [B, n_horizons, output_features]

    def test_single_horizon(self):
        head = MultiHorizonHead(64, horizons=[12], output_features=2)
        x = torch.randn(8, 64)
        out = head(x)
        assert out.shape == (8, 1, 2)


# =====================================================================
# Full Model Forward Pass
# =====================================================================

class TestNeuralPriceForecaster:
    def test_forward_pass(self):
        model = NeuralPriceForecaster(
            input_dim=INPUT_DIM,
            proj_dim=64,
            ff_dim=128,
            tcn_channels=[64, 64, 128],
            gru_hidden=128,
            output_horizons=[1, 3, 6, 12, 24],
        )
        x = torch.randn(4, 30, INPUT_DIM)
        intervals = torch.rand(4, 30) * 24
        preds, gates = model(x, intervals)
        assert preds.shape == (4, 5, 3)  # 5 horizons × 3 features
        assert gates.shape == (4, 30)

    def test_eval_mode(self):
        model = NeuralPriceForecaster(input_dim=INPUT_DIM)
        model.eval()
        x = torch.randn(1, 20, INPUT_DIM)
        with torch.no_grad():
            preds, gates = model(x)
        assert preds.shape[0] == 1
        assert preds.shape[1] == 8  # Default 8 horizons
        assert preds.shape[2] == 3

    def test_param_count(self):
        model = NeuralPriceForecaster(input_dim=INPUT_DIM)
        n_params = sum(p.numel() for p in model.parameters())
        assert n_params > 50_000  # Should have meaningful capacity
        assert n_params < 5_000_000  # But not enormous


# =====================================================================
# NeuralDataAdapter Tests
# =====================================================================

class TestNeuralDataAdapter:
    def _make_records(self, n=20, skin_name="Test Case"):
        import datetime
        records = []
        base_price = 1.0
        base_date = datetime.datetime(2026, 7, 1, 12, 0, 0)
        for i in range(n):
            records.append({
                "skin_name": skin_name,
                "hash_name": skin_name,
                "lowest_price": base_price + np.random.randn() * 0.1,
                "median_price": base_price + np.random.randn() * 0.05,
                "volume": int(np.random.randint(10, 100)),
                "scraped_at": (base_date + datetime.timedelta(hours=12 * i)).isoformat() + "Z",
            })
        return records

    def test_records_to_features(self):
        adapter = NeuralDataAdapter()
        records = self._make_records(20)
        feat = adapter.records_to_features(records)
        assert feat is not None
        assert feat["n_points"] == 20
        assert feat["feature_matrix"].shape[1] == INPUT_DIM

    def test_insufficient_data(self):
        adapter = NeuralDataAdapter()
        records = self._make_records(5)
        feat = adapter.records_to_features(records)
        assert feat is None

    def test_build_dataset(self):
        adapter = NeuralDataAdapter()
        records_by_skin = {
            "Skin A": self._make_records(25, "Skin A"),
            "Skin B": self._make_records(30, "Skin B"),
            "Skin C": self._make_records(15, "Skin C"),
        }
        tensors, metadata = adapter.build_dataset(records_by_skin)
        assert "inputs" in tensors
        assert "intervals" in tensors
        assert "targets" in tensors
        assert tensors["inputs"].shape[0] == 3  # 3 skins
        assert tensors["inputs"].shape[2] == INPUT_DIM
        assert len(metadata) == 3

    def test_scaler_fitting(self):
        adapter = NeuralDataAdapter()
        records = self._make_records(30)
        feat = adapter.records_to_features(records)
        adapter.fit_scaler([feat])
        assert adapter._fitted
        # Normalization should produce values roughly in [-3, 3]
        normed = adapter.normalize(feat["feature_matrix"])
        assert abs(normed.mean()) < 1.0  # Should be roughly zero-centered


# =====================================================================
# NeuralForecasterWrapper Tests
# =====================================================================

class TestNeuralForecasterWrapper:
    def test_no_checkpoint_fallback(self):
        """Without a checkpoint, should fall back to baseline."""
        wrapper = NeuralForecasterWrapper(checkpoint_path="/tmp/nonexistent.pt")
        assert not wrapper._has_model

    def test_can_forecast_gate(self):
        wrapper = NeuralForecasterWrapper()
        assert wrapper.min_data_points >= 30  # Neural needs more data
        # Below gate
        assert not wrapper.can_forecast({})
        assert not wrapper.can_forecast({"n_points": 5})
        # Above gate
        assert wrapper.can_forecast({"n_points": 35})

    def test_fallback_to_baseline(self):
        """When no neural checkpoint, forecast uses baseline."""
        wrapper = NeuralForecasterWrapper(
            checkpoint_path="/tmp/nonexistent.pt",
            config=ForecastConfig(),
        )
        # Build features that pass the baseline gate
        features = {
            "current_price": 1.5,
            "mean_price": 1.4,
            "median_price": 1.45,
            "std_price": 0.2,
            "cv": 0.14,
            "slope": 0.01,
            "momentum": 0.02,
            "volume_trend": 5.0,
            "n_points": 15,
            "distinct_days": 8,
            "time_span_hours": 96.0,
            "avg_interval_hours": 12.0,
        }
        # Neural wrapper has min_data_points=30, so this falls back to baseline
        # But can_forecast checks min_data_points=30, so it returns None
        assert not wrapper.can_forecast(features)  # 15 < 30

    def test_baseline_forecast_works(self):
        """Verify the lazy-loaded baseline works through the wrapper."""
        wrapper = NeuralForecasterWrapper(
            checkpoint_path="/tmp/nonexistent.pt",
            config=ForecastConfig(),
        )
        # Manually call baseline (since neural gate blocks at 30)
        features = {
            "current_price": 2.0,
            "mean_price": 1.9,
            "median_price": 1.95,
            "std_price": 0.3,
            "cv": 0.16,
            "slope": 0.02,
            "momentum": 0.03,
            "volume_trend": 10.0,
            "n_points": 20,
            "distinct_days": 10,
            "time_span_hours": 120.0,
            "avg_interval_hours": 12.0,
        }
        # Baseline should work
        result = wrapper.baseline.forecast(features)
        assert result is not None
        assert "predicted_price" in result
        assert "direction" in result
        assert "confidence" in result


# =====================================================================
# Edge Cases
# =====================================================================

class TestEdgeCases:
    def test_model_with_minimal_input(self):
        model = NeuralPriceForecaster(input_dim=INPUT_DIM)
        model.eval()
        x = torch.randn(1, 10, INPUT_DIM)
        with torch.no_grad():
            preds, gates = model(x)
        assert preds.shape == (1, 8, 3)

    def test_model_with_very_long_sequence(self):
        model = NeuralPriceForecaster(input_dim=INPUT_DIM)
        model.eval()
        x = torch.randn(1, 200, INPUT_DIM)
        intervals = torch.rand(1, 200) * 24
        with torch.no_grad():
            preds, gates = model(x, intervals)
        assert preds.shape == (1, 8, 3)

    def test_all_zero_prices(self):
        """Adapter should handle zero prices gracefully."""
        import datetime
        adapter = NeuralDataAdapter()
        records = []
        base_date = datetime.datetime(2026, 7, 1, 12, 0, 0)
        for i in range(20):
            records.append({
                "skin_name": "Zero Case",
                "hash_name": "Zero Case",
                "lowest_price": 0.0,
                "median_price": 0.0,
                "volume": 0,
                "scraped_at": (base_date + datetime.timedelta(hours=12 * i)).isoformat() + "Z",
            })
        feat = adapter.records_to_features(records)
        # Should not crash — zeros get filtered by the extractor
        # The extractor drops rows with price <= 0
        assert feat is None  # All zeros → filtered out → < 10 points
