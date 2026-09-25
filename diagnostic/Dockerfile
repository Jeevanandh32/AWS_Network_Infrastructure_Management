FROM alpine:3.22

RUN apk add --no-cache \
    tcpdump \
    curl \
    bind-tools \
    iproute2 \
    iputils

WORKDIR /captures

COPY diagnose.sh /usr/local/bin/diagnose.sh

CMD ["sleep", "infinity"]
