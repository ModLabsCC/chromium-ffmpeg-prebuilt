FROM ubuntu:24.04

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        binutils build-essential ca-certificates file git nasm pkg-config python3 xz-utils yasm \
    && rm -rf /var/lib/apt/lists/*
