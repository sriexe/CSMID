"""
src/app.py — FastAPI Web Service for CSMID Market Copilot

Exposes REST API endpoints and a chat router interface for CSMIDMarketAgent.
"""

import os
import re
import logging
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from src.agent import CSMIDMarketAgent
load_dotenv()
# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CSMID.api")

# Initialize FastAPI App
app = FastAPI(
    title="CSMID Market Copilot API",
    description="REST API & Chat Router for CS2 Predictive Market Intelligence",
    version="1.0.0",
)

# Enable CORS for Streamlit / Web Frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Agent Instance
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://your-supabase-url.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "your-supabase-anon-key")

agent: Optional[CSMIDMarketAgent] = None


@app.on_event("startup")
def startup_event():
    """Initialize CSMIDMarketAgent on application startup."""
    global agent
    try:
        agent = CSMIDMarketAgent(supabase_url=SUPABASE_URL, supabase_key=SUPABASE_KEY)
        logger.info("CSMIDMarketAgent successfully initialized.")
    except Exception as exc:
        logger.error("Failed to initialize agent: %s", exc)


# =====================================================================
# PYDANTIC SCHEMAS
# =====================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., example="How is Glock-18 Block-18 looking? I have $30 to spend.")
    budget: Optional[float] = Field(default=None, example=30.0)
    min_accuracy: Optional[float] = Field(default=90.0, example=90.0)


class ChatResponse(BaseModel):
    query: str
    reply: str
    tool_data: Optional[Dict[str, Any]] = None


# =====================================================================
# DIRECT REST ENDPOINTS
# =====================================================================

@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """Service health verification."""
    return {"status": "healthy", "agent_connected": agent is not None}


@app.get("/api/v1/inspect/{skin_name:path}")
def inspect_skin(skin_name: str):
    """Fetch current price, forecaster predictions, and metrics for a specific skin."""
    if not agent:
        raise HTTPException(status_code=500, detail="Agent service uninitialized.")
    result = agent.inspect_skin(skin_name)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/v1/recommendations")
def get_recommendations(
    budget: float = Query(..., description="Maximum budget in USD"),
    top_n: int = Query(3, description="Number of items to return")
):
    """Retrieve budget-filtered buy recommendations ranked by model accuracy and return."""
    if not agent:
        raise HTTPException(status_code=500, detail="Agent service uninitialized.")
    return agent.recommend_buys_by_budget(max_budget_usd=budget, top_n=top_n)


@app.get("/api/v1/sell-alerts")
def get_sell_alerts(
    min_accuracy: float = Query(90.0, description="Minimum directional accuracy percentage")
):
    """Get high-confidence sell signals for portfolio items or cases."""
    if not agent:
        raise HTTPException(status_code=500, detail="Agent service uninitialized.")
    return agent.check_high_confidence_sells(min_accuracy_pct=min_accuracy)


# =====================================================================
# CHAT ROUTER ENDPOINT
# =====================================================================

@app.post("/api/v1/chat", response_model=ChatResponse)
def process_chat(request: ChatRequest):
    """
    Main conversational endpoint: Parses natural language input and invokes
    relevant agent tools.
    """
    if not agent:
        raise HTTPException(status_code=500, detail="Agent service uninitialized.")

    text = request.message.lower()
    tool_payload = {}
    reply_lines = []

    # 1. Intent Detection: Budget Buy Query
    budget_match = re.search(r"\$(\d+(?:\.\d{1,2})?)", text)
    budget = request.budget or (float(budget_match.group(1)) if budget_match else None)

    if "buy" in text or "recommend" in text or budget is not None:
        target_budget = budget or 50.0
        recs = agent.recommend_buys_by_budget(max_budget_usd=target_budget)
        tool_payload["recommendations"] = recs
        
        items = recs.get("recommended_buys", [])
        if items:
            reply_lines.append(f"💡 **Buy Recommendations (Under ${target_budget:.2f}):**")
            for item in items:
                reply_lines.append(
                    f"• **{item['skin_name']}**: ${item['price_usd']:.2f} ➔ Target ${item['target_price_usd']:.2f} "
                    f"(+{item['projected_gain_pct']}% upside, {item['model_direction_accuracy']} Direction Acc)"
                )
        else:
            reply_lines.append(f"No high-confidence buy candidates found under ${target_budget:.2f}.")

    # 2. Intent Detection: Sell / Case Check
    if "sell" in text or "alert" in text or "case" in text:
        min_acc = request.min_accuracy or 90.0
        sells = agent.check_high_confidence_sells(min_accuracy_pct=min_acc)
        tool_payload["sell_alerts"] = sells
        
        alerts = sells.get("active_sell_alerts", [])
        if alerts:
            reply_lines.append(f"\n🚨 **High-Confidence Sell Alerts ({min_acc}%+ Acc):**")
            for a in alerts:
                reply_lines.append(
                    f"• **{a['skin_name']}**: Current ${a['current_price']:.2f} | "
                    f"Cost Basis ${a['cost_basis_usd']} | Action: **{a['action_required']}** "
                    f"({a['model_accuracy_confidence']} Acc)"
                )
        else:
            reply_lines.append(f"\n✅ No sell triggers detected above {min_acc}% accuracy.")

    # 3. Intent Detection: Specific Skin Search (e.g. "glock", "ak-47")
    if "glock" in text or "block" in text or "inspect" in text:
        skin_query = "Glock-18 | Block-18 (Field-Tested)"  # Default example fallback
        if "block-18" in text or "block 18" in text:
            skin_query = "Glock-18 | Block-18 (Field-Tested)"
            
        inspection = agent.inspect_skin(skin_query)
        tool_payload["skin_inspection"] = inspection
        
        if "error" not in inspection:
            reply_lines.append(
                f"\n🔍 **{inspection['skin_name']} Overview:**\n"
                f"• Current Price: ${inspection['current_price']:.2f}\n"
                f"• Forecasted Target: ${inspection['predicted_price']:.2f}\n"
                f"• Signal: **{inspection['signal']}**\n"
                f"• Backtest Accuracy: {inspection['historical_direction_accuracy']}\n"
                f"• Analysis: {inspection['summary']}"
            )

    # Fallback if no specific intent matched
    if not reply_lines:
        reply_lines.append(
            "I'm ready! You can ask me to inspect a skin (e.g. *Glock-18 Block-18*), "
            "request buy recommendations with a budget (e.g. *$40 budget*), or check "
            "high-confidence sell alerts for your inventory."
        )

    return ChatResponse(
        query=request.message,
        reply="\n".join(reply_lines),
        tool_data=tool_payload
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.app:app", host="0.0.0.0", port=8000, reload=True)