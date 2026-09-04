FROM golang:1.27-bookworm AS build
WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 go build -o /search-fetcher ./cmd/search-fetcher
FROM gcr.io/distroless/static-debian12
COPY --from=build /search-fetcher /search-fetcher
EXPOSE 8082
ENTRYPOINT ["/search-fetcher"]
