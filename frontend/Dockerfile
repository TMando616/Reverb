# syntax=docker/dockerfile:1
# ローカル開発用（next dev）。本番向けのマルチステージ化は AWS 構成を決めるとき（ADR-0003）に行う。
FROM node:24-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
