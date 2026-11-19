# PackVault keeper image (Fly.io worker, as apeball's keepers). Built from the repository root:
#   fly deploy --config fly.keeper-primary.toml
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git && rm -rf /var/lib/apt/lists/*
# cast, pinned to the version the keeper was tested with
# FOUNDRY_DIR pins the install location; newer installers otherwise choose ~/.config/.foundry.
ENV FOUNDRY_DIR=/root/.foundry
RUN curl -L https://foundry.paradigm.xyz | bash && /root/.foundry/bin/foundryup --install 1.8.1
ENV PATH="/root/.foundry/bin:${PATH}"
WORKDIR /app
COPY keeper/requirements.txt ./keeper/requirements.txt
RUN python3 -m pip install --no-cache-dir -r keeper/requirements.txt
COPY keeper/*.py ./keeper/
COPY keeper/entrypoint.sh ./keeper/
RUN python3 keeper/keeper.py --help > /dev/null
CMD ["sh", "keeper/entrypoint.sh"]
