import os
import threading

from .config import SCORES_FILE

# Shared score store: { user_id (int): {"name": str, "score": int} }
scores: dict = {}
scores_lock = threading.Lock()


def load_scores() -> None:
    if not os.path.exists(SCORES_FILE):
        return
    with open(SCORES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|") or line.startswith("| Rank") or line.startswith("|---"):
                continue
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) == 4:
                try:
                    _, name, score, user_id = parts
                    scores[int(user_id)] = {"name": name, "score": int(score)}
                except ValueError:
                    continue


def save_scores() -> None:
    lines = [
        "# TriviaOracleBot Scoreboard\n",
        "| Rank | Name | Score | Telegram ID |\n",
        "|------|------|-------|-------------|\n",
    ]
    for rank, (uid, player) in enumerate(_ranked(), start=1):
        lines.append(f"| {rank} | {player['name']} | {player['score']} | {uid} |\n")
    os.makedirs(os.path.dirname(SCORES_FILE) or ".", exist_ok=True)
    with open(SCORES_FILE, "w") as f:
        f.writelines(lines)


def _ranked() -> list:
    """(user_id, player) pairs, highest score first — the order shown on the scoreboard."""
    return sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)


def medalist_ids() -> set:
    """User IDs currently shown with 🥇🥈🥉 on the scoreboard."""
    return {uid for uid, _ in _ranked()[:3]}


def format_scoreboard() -> str:
    if not scores:
        return "📊 Scoreboard\n\nNo scores yet!"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["📊 Scoreboard\n"]
    for rank, (_, player) in enumerate(_ranked(), start=1):
        lines.append(f"{medals.get(rank, f'{rank}.')} {player['name']} — {player['score']} pts")
    return "\n".join(lines)
