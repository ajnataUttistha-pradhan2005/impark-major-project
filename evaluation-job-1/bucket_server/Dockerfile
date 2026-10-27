FROM alpine:latest
RUN apk add --no-cache python3
WORKDIR /app
COPY server.py /app/
EXPOSE 9000 9001
CMD ["python3", "server.py"]
