FROM alpine:3.22
RUN apk add --no-cache android-tools
CMD ["adb", "-L", "tcp:localhost:5037", "nodaemon", "server"]
