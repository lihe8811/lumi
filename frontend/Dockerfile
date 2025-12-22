FROM oven/bun:1.1.13

WORKDIR /app

COPY package.json bun.lock /app/
RUN bun install

COPY . /app

EXPOSE 4201

CMD ["bun", "run", "serve", "--", "--port", "4201", "--host", "0.0.0.0"]
