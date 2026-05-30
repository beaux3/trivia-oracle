


Build:
docker build -t chewterence/trivia-oracle:latest .

Run:
docker run --rm chewterence/trivia-oracle:latest


docker build -t chewterence/trivia-oracle:latest . && docker run --rm chewterence/trivia-oracle:latest

Push to docker hub:
docker push chewterence/trivia-oracle:latest


docker logout
rm -rf ~/.docker/config.json
docker login   # use access token
docker push chewterence/trivia-oracle:latest