FROM cloakhq/cloakbrowser:latest

RUN groupadd --system --gid 1000 astra \
    && useradd --system --uid 1000 --gid 1000 --create-home --home-dir /home/astra astra \
    && mkdir -p /app /profile /home/astra/.cache \
    && chown -R astra:astra /app /profile /home/astra

WORKDIR /app
COPY app.py /app/app.py
COPY entrypoint-nonroot.sh /entrypoint-nonroot.sh
RUN chmod 0755 /entrypoint-nonroot.sh

EXPOSE 43104 9222

ENTRYPOINT ["/entrypoint-nonroot.sh"]
CMD ["python", "/app/app.py"]
