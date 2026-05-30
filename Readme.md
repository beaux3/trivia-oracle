# TriviaOracleBot 🎯

A Telegram trivia bot built just for fun by **Terence Chew**. Questions are pulled live from the [qbreader](https://www.qbreader.org) database and revealed sentence by sentence — buzz in by typing your answer before the clue runs out.

100% vibe coded. No regrets.

---

## Features

- Tossup questions across dozens of categories (Literature, History, Science, Arts, Pop Culture, and more)
- Configurable categories, difficulty levels, and timing via `/configure`
- Simultaneous correct answers all get credited
- Persistent scoreboard across sessions

---

## Running it yourself

The bot is fully portable — all you need is Docker.

### 1. Clone the repo and build the image

```bash
docker build -t trivia-oracle .
```

### 2. Run it

```bash
docker run --rm trivia-oracle
```

That's it. The bot will start polling Telegram immediately.

> **Note:** Scores are saved to `/app/scores.md` inside the container.
> If you want scores to survive container restarts, mount a volume:
> ```bash
> docker run --rm -v $(pwd)/data:/app trivia-oracle
> ```

---

## Bot commands

| Command | Description |
|---------|-------------|
| `/next` | Start a new round |
| `/scores` | Show the current scoreboard |
| `/configure` | Configure categories, difficulty, and timing |

---

## Publishing to Docker Hub

```bash
docker build -t chewterence/trivia-oracle:latest .
docker login          # use your access token
docker push chewterence/trivia-oracle:latest
```
