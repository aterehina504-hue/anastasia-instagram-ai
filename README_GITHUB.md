# GitHub quick start

## Create the repository

1. Create a **private** repository on GitHub, e.g. `anastasia-instagram-ai`.
2. Do not initialize it with a README (this project already has one).
3. Unzip this project, open a terminal in the project folder and run:

```bash
git init
git add .
git status  # confirm .env is NOT listed
git commit -m "Initial Instagram AI content factory"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/anastasia-instagram-ai.git
git push -u origin main
```

Use a private repository because configuration may reveal business workflows. The `.env` file is ignored by Git. Store production secrets in the server environment or GitHub Actions Secrets, never in source files.

## Local run

```bash
cp .env.example .env
# edit .env with your own API credentials
docker compose up --build -d
```

GitHub Actions runs pytest on pushes and pull requests. It does not publish to Instagram.

## Important

This project is configured for the Instagram profile as an initial content-creator brand profile. The niche, offer, services, voice and visual identity must be filled with verified information before generating production content. Publishing always requires manual approval in the app.
