"""
Generic time-series forecasting used for BOTH product demand and business sales.

Design (explained in docs/ML_AND_ANALYTICS.md):
  * Direct multi-horizon forecasting: every feature is built from values at least
    ``horizon`` days old, so predicting day t+1..t+H never needs a recursive guess.
  * Time-based split: the LAST ``holdout_days`` days are the test set. Never a random split
    (a random split leaks the future into training).
  * Baselines first. A complex model is only chosen if it beats them on held-out data.
  * Metrics: MAE, RMSE and WAPE (= sum|error| / sum(actual)). MAPE is NOT used for demand
    because daily demand contains many zeros (division by zero / meaningless percentages).
  * Because the app acts on the TOTAL demand over the horizon (e.g. 7 days), candidates are also
    scored on non-overlapping horizon-length blocks ("block_*" metrics). Daily demand of a slow
    product is mostly random noise; totals are what a shop owner can actually plan with.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

BASELINES = ["seasonal_naive", "mean_28d", "group_mean", "dow_mean"]
GBM_NAME = "gradient_boosting"


def feature_columns(horizon):
    return [f"lag_{horizon}", f"lag_{horizon + 7}", f"lag_{horizon + 14}", "roll7", "roll28", "dow", "dom", "month", "gmean", "dow_mean"]


def make_features(df, horizon):
    df = df.sort_values(["group", "date"]).reset_index(drop=True).copy()
    g = df.groupby("group")["y"]
    for off in (0, 7, 14):
        df[f"lag_{horizon + off}"] = g.shift(horizon + off)
    df["roll7"] = g.transform(lambda s: s.shift(horizon).rolling(7, min_periods=7).mean())
    df["roll28"] = g.transform(lambda s: s.shift(horizon).rolling(28, min_periods=14).mean())
    df["dow"] = df["date"].dt.dayofweek
    df["dom"] = df["date"].dt.day
    df["month"] = df["date"].dt.month
    return df


def attach_means(feats, source):
    """gmean / dow_mean computed ONLY from `source` rows (the training period) -> no leakage."""
    source = source.dropna(subset=["y"])
    gm = source.groupby("group")["y"].mean()
    dm = source.groupby(["group", "dow"])["y"].mean().rename("dow_mean").reset_index()
    out = feats.drop(columns=[c for c in ("gmean", "dow_mean") if c in feats.columns])
    out["gmean"] = out["group"].map(gm)
    return out.merge(dm, on=["group", "dow"], how="left")


def _block_metrics(test, preds, horizon):
    """Score totals over non-overlapping `horizon`-day blocks (complete blocks only)."""
    start = test["date"].min()
    frame = pd.DataFrame({"group": test["group"].to_numpy(), "blk": ((test["date"] - start).dt.days // horizon).to_numpy(),
                          "y": test["y"].to_numpy()})
    for name, p in preds.items():
        frame[name] = p
    agg = frame.groupby(["group", "blk"]).agg(n=("y", "size"), **{c: (c, "sum") for c in ["y", *preds]})
    agg = agg[agg["n"] == horizon]
    if agg.empty:
        return {}
    return {name: _metrics(agg["y"].to_numpy(), agg[name].to_numpy()) for name in preds}


def _metrics(actual, pred):
    err = np.asarray(actual, dtype=float) - np.asarray(pred, dtype=float)
    denom = float(np.sum(np.abs(actual)))
    return {
        "mae": round(float(np.mean(np.abs(err))), 4),
        "rmse": round(float(np.sqrt(np.mean(err ** 2))), 4),
        "wape": round(float(np.sum(np.abs(err)) / denom), 4) if denom > 0 else None,
    }


def _new_model():
    return GradientBoostingRegressor(n_estimators=150, max_depth=3, learning_rate=0.05, subsample=0.8, random_state=42)


def _baseline_pred(frame, name, horizon):
    if name == "seasonal_naive":
        return frame[f"lag_{horizon}"].to_numpy()
    if name == "mean_28d":
        return frame["roll28"].to_numpy()
    if name == "dow_mean":
        return frame["dow_mean"].to_numpy()
    return frame["gmean"].to_numpy()


def evaluate_and_forecast(df, horizon, holdout_days=28, min_train_rows=60, min_test_rows=14, min_nonzero_days=8,
                          select_by="mae"):
    """
    df: dense frame with columns [group, date, y] ending at the last complete day.
    Returns None when there is not enough history, else a result dict.
    """
    if df.empty:
        return None
    end = df["date"].max()
    cutoff = end - pd.Timedelta(days=holdout_days)
    cols = feature_columns(horizon)

    feats = make_features(df, horizon)
    feats = attach_means(feats, feats[feats["date"] <= cutoff])  # training period only: no leakage
    valid = feats.dropna(subset=cols)
    train, test = valid[valid["date"] <= cutoff], valid[valid["date"] > cutoff]

    nonzero = df[df["y"] > 0].groupby("group").size()
    counts_tr, counts_te = train.groupby("group").size(), test.groupby("group").size()
    eligible = [
        gid for gid in counts_te.index
        if counts_te.get(gid, 0) >= min_test_rows and counts_tr.get(gid, 0) >= 30 and nonzero.get(gid, 0) >= min_nonzero_days
    ]
    train, test = train[train["group"].isin(eligible)], test[test["group"].isin(eligible)]
    if len(train) < min_train_rows or len(test) < min_test_rows or not eligible:
        return None

    preds, results = {}, {}
    for name in BASELINES:
        preds[name] = np.clip(_baseline_pred(test, name, horizon), 0, None)
    gbm = _new_model().fit(train[cols], train["y"])
    preds[GBM_NAME] = np.clip(gbm.predict(test[cols]), 0, None)
    for name, p in preds.items():
        results[name] = _metrics(test["y"].to_numpy(), p)
    blocks = _block_metrics(test, preds, horizon)
    for name, m in blocks.items():
        results[name].update({f"block_{k}": v for k, v in m.items()})
    metric = select_by if select_by in results[BASELINES[0]] else "mae"

    selected = BASELINES[0]
    for name in BASELINES + [GBM_NAME]:  # strict "<": ties go to the simpler method
        if results[name][metric] < results[selected][metric]:
            selected = name
    residuals = test["y"].to_numpy() - preds[selected]
    resid_q = (float(np.quantile(residuals, 0.10)), float(np.quantile(residuals, 0.90)))

    # ---- final forecast for the next `horizon` days ----
    full_mean = df.groupby("group")["y"].mean()
    future_rows = [
        {"group": gid, "date": end + pd.Timedelta(days=i), "y": np.nan}
        for gid in eligible for i in range(1, horizon + 1)
    ]
    ext = pd.concat([df[df["group"].isin(eligible)], pd.DataFrame(future_rows)], ignore_index=True)
    ext = make_features(ext, horizon)
    ext = attach_means(ext, ext[ext["date"] <= end])
    future = ext[ext["date"] > end].copy()
    future = future.dropna(subset=cols)
    model = None
    if selected == GBM_NAME:
        full_valid = ext[(ext["date"] <= end)].dropna(subset=cols + ["y"])
        model = _new_model().fit(full_valid[cols], full_valid["y"])  # refit on ALL data before forecasting
        future["yhat"] = np.clip(model.predict(future[cols]), 0, None)
    else:
        future["yhat"] = np.clip(_baseline_pred(future, selected, horizon), 0, None)
    future["yhat"] = future["yhat"].fillna(0)

    return {
        "metrics": results,
        "selected": selected,
        "forecast": future[["group", "date", "yhat"]].reset_index(drop=True),
        "eligible": set(eligible),
        "selected_by": metric,
        "residual_q": resid_q,
        "model": model,
        "gmean": full_mean.to_dict(),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "data_end": end.date(),
        "holdout_days": holdout_days,
    }
