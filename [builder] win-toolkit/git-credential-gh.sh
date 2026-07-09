#!/usr/bin/env bash
# Git credential helper for GitHub: extracts token from GITHUB_TOKEN env
# Conforms to git credential protocol (read k=v pairs until blank line)

case "$1" in
    get)
        host=""
        protocol=""
        while IFS='=' read -r key value; do
            if [ -z "$key" ]; then
                # blank line -> end of request
                break
            fi
            case "$key" in
                host) host="$value" ;;
                protocol) protocol="$value" ;;
            esac
        done
        if [ "$host" = "github.com" ] && [ -n "$GITHUB_TOKEN" ]; then
            echo "username=token"
            echo "password=$GITHUB_TOKEN"
        fi
        ;;
    store|erase)
        # no-op: token is ephemeral from env var
        exit 0
        ;;
esac
