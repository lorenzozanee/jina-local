FROM rust:1.85-bookworm AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
COPY --from=build /src/target/release/jina-search-core /usr/local/bin/jina-search-core
EXPOSE 8083
CMD ["jina-search-core"]
