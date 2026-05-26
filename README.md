# Tasker

API REST minimale per gestire una lista di task, scritta in Python/Flask con
persistenza su PostgreSQL. Pensata per essere deployata su Kubernetes (AWS EKS)
in alta disponibilità, con pipeline CI/CD via GitHub Actions.

## Stack

- **Python 3.12** · Flask + SQLAlchemy + psycopg2
- **PostgreSQL 16** · single-pod oppure cluster HA via CloudNativePG
- **Docker** · immagine multi-arch, deploy arm64 su AWS Graviton
- **Kubernetes (AWS EKS)** · deploy in produzione
- **GitHub Actions** · CI/CD con autenticazione OIDC su AWS (no chiavi statiche)

## Endpoint

| Metodo | Path | Descrizione |
|---|---|---|
| GET | `/` | info del servizio |
| GET | `/health` | health check (verifica anche la connessione al DB) |
| GET | `/tasks` | lista tutte le task |
| POST | `/tasks` | crea una task `{title, description?}` |
| GET | `/tasks/<id>` | dettaglio di una task |
| PATCH | `/tasks/<id>` | aggiorna `done`, `title` o `description` |
| DELETE | `/tasks/<id>` | elimina una task |

## Configurazione

Variabili d'ambiente richieste:

- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`
- `POSTGRES_PASSWORD` *oppure* `POSTGRES_PASSWORD_FILE` (path a un file)

La convenzione `_FILE` permette di leggere la password da un file montato (es.
Secrets Store CSI Driver in modo canonico), evitando di passare la password
come variabile d'ambiente o come Secret Kubernetes sincronizzato.

## Struttura del repository

```
.
├── app.py                          # applicazione Flask
├── requirements.txt
├── Dockerfile                      # build multi-arch (arm64 per Graviton)
│
├── postgres-*.yaml                 # manifest Postgres single-pod (versione base)
├── postgres-cluster-cnpg.yaml      # cluster Postgres HA via CloudNativePG
├── postgres-secretproviderclass.yaml
├── postgres-serviceaccount.yaml
│
├── tasker-deployment-eks.yaml      # Deployment Tasker (3 repliche, HA, probe)
├── tasker-hpa.yaml                 # HorizontalPodAutoscaler
├── tasker-pdb.yaml                 # PodDisruptionBudget
├── tasker-service-loadbalancer-eks.yaml
├── tasker-serviceaccount.yaml
├── storageclass-gp3.yaml           # StorageClass EBS gp3 default
│
└── .github/workflows/deploy.yaml   # pipeline CI/CD GitHub Actions
```

## Avvio in locale

Richiede Docker e un Postgres raggiungibile.

```bash
pip install -r requirements.txt
export POSTGRES_HOST=localhost POSTGRES_PORT=5432
export POSTGRES_DB=tasker POSTGRES_USER=tasker POSTGRES_PASSWORD=...
python app.py
```

## Build immagine arm64

```bash
docker buildx build --platform linux/arm64 -t tasker:dev --load .
```

## Deploy su Kubernetes

Vedi i manifest YAML in radice. Ordine consigliato di apply:

1. `*-serviceaccount.yaml`
2. `storageclass-gp3.yaml`, `postgres-configmap.yaml`
3. `postgres-secretproviderclass.yaml`
4. Database: `postgres-*.yaml` (single-pod) **oppure** `postgres-cluster-cnpg.yaml`
5. `postgres-service.yaml`
6. `tasker-deployment-eks.yaml`, `tasker-pdb.yaml`, `tasker-hpa.yaml`
7. `tasker-service-loadbalancer-eks.yaml`

## CI/CD

`.github/workflows/deploy.yaml` builda l'immagine arm64, la pusha su ECR con
tag = SHA del commit, e aggiorna il deployment su EKS. L'autenticazione su
AWS avviene via OIDC federation: nessuna chiave statica nei Secrets di GitHub.

Setup AWS (IAM role OIDC, EKS Access Entry) e materiali editoriali della serie
sono in `~/Repository/personal/BreakingProd-materiali/`.
