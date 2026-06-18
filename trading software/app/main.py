"""FastAPI application: leaderboard, transparent prediction log, JSON API."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import ASSETS, ASSETS_BY_SYMBOL, get_settings
from app.db import SessionLocal, init_db
from app.engine.evaluator import run_evaluations
from app.engine.predictor import run_predictions
from app.engine.scoreboard import Stat, full_scoreboard, known_models, list_predictions
from app.scheduler import shutdown_scheduler, start_scheduler

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="News-Driven Stock Prediction Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


# --- Template helpers ---
def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") + " UTC" if value else "—"


def _fmt_price(value: float | None) -> str:
    return f"{value:,.2f}" if value is not None else "—"


templates.env.filters["dt"] = _fmt_dt
templates.env.filters["price"] = _fmt_price
templates.env.filters["fromjson"] = lambda s: json.loads(s) if s else []


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- Pages ---
@app.get("/", response_class=HTMLResponse)
def leaderboard(request: Request, h: str = "24h", db: Session = Depends(get_db)):
    data = full_scoreboard(db)
    if h not in data["horizons"]:
        h = data["horizons"][0]
    return templates.TemplateResponse(
        request,
        "leaderboard.html",
        {
            "data": data,
            "active_horizon": h,
            "settings": get_settings(),
            "active_page": "leaderboard",
        },
    )


@app.get("/predictions", response_class=HTMLResponse)
def predictions_page(
    request: Request,
    asset: str | None = None,
    model: str | None = None,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request,
        "predictions.html",
        {
            "predictions": list_predictions(db, asset=asset, model=model),
            "assets": ASSETS,
            "models": known_models(db),
            "selected_asset": asset,
            "selected_model": model,
            "active_page": "predictions",
        },
    )


@app.get("/asset/{symbol}", response_class=HTMLResponse)
def asset_page(symbol: str, request: Request, db: Session = Depends(get_db)):
    symbol = symbol.upper()
    asset = ASSETS_BY_SYMBOL.get(symbol)
    if asset is None:
        raise HTTPException(status_code=404, detail="Unknown asset")

    board = full_scoreboard(db)
    asset_stats = {
        h: next((s for s in board["boards"][h]["by_asset"] if s.label == symbol), None)
        for h in board["horizons"]
    }
    return templates.TemplateResponse(
        request,
        "asset.html",
        {
            "asset": asset,
            "horizons": board["horizons"],
            "asset_stats": asset_stats,
            "predictions": list_predictions(db, asset=symbol, limit=100),
            "active_page": "",
        },
    )


# --- JSON API ---
def _stat_dict(s: Stat | None) -> dict | None:
    if s is None:
        return None
    return {
        "label": s.label,
        "correct": s.correct,
        "incorrect": s.incorrect,
        "pending": s.pending,
        "push": s.push,
        "decided": s.decided,
        "total": s.total,
        "accuracy": s.accuracy,
    }


@app.get("/api/scoreboard")
def api_scoreboard(db: Session = Depends(get_db)):
    data = full_scoreboard(db)
    out: dict = {"horizons": data["horizons"], "boards": {}}
    for h, b in data["boards"].items():
        out["boards"][h] = {
            "overall": _stat_dict(b["overall"]),
            "overall_30d": _stat_dict(b["overall_30d"]),
            "overall_90d": _stat_dict(b["overall_90d"]),
            "by_asset": [_stat_dict(s) for s in b["by_asset"]],
            "by_model": [_stat_dict(s) for s in b["by_model"]],
            "best_model": _stat_dict(b["best_model"]),
            "worst_model": _stat_dict(b["worst_model"]),
        }
    return out


@app.get("/api/predictions")
def api_predictions(
    asset: str | None = None,
    model: str | None = None,
    db: Session = Depends(get_db),
):
    preds = list_predictions(db, asset=asset, model=model)
    return [
        {
            "id": p.id,
            "created_at": p.created_at.isoformat(),
            "asset": p.asset,
            "model": p.model,
            "direction": p.direction,
            "bullish_prob": p.bullish_prob,
            "bearish_prob": p.bearish_prob,
            "price_at_prediction": p.price_at_prediction,
            "rationale": p.rationale,
            "news_count": len(json.loads(p.news_snapshot) if p.news_snapshot else []),
            "evaluations": [
                {
                    "horizon": e.horizon,
                    "status": e.status,
                    "target_eval_time": e.target_eval_time.isoformat(),
                    "price_at_eval": e.price_at_eval,
                    "actual_direction": e.actual_direction,
                    "is_correct": e.is_correct,
                }
                for e in p.evaluations
            ],
        }
        for p in preds
    ]


@app.post("/api/run-predictions")
def api_run_predictions(db: Session = Depends(get_db)):
    return JSONResponse(run_predictions(db))


@app.post("/api/run-evaluations")
def api_run_evaluations(db: Session = Depends(get_db)):
    return JSONResponse(run_evaluations(db))
