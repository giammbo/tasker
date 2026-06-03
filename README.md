# Tasker

API REST minimale per gestire una lista di task, scritta in Python/Flask con
persistenza su PostgreSQL. Pensata per essere deployata su Kubernetes (AWS EKS)
in alta disponibilità, con pipeline CI/CD via GitHub Actions e deploy
progressivi (canary) via Argo Rollouts.

## Stack

- **Python 3.12** · Flask + SQLAlchemy + psycopg2
- **PostgreSQL 16** · single-pod oppure cluster HA via CloudNativePG
- **Docker** · immagine multi-arch, deploy arm64 su AWS Graviton
- **Kubernetes (AWS EKS)** · deploy in produzione
- **GitHub Actions** · CI/CD con autenticazione OIDC su AWS (no chiavi statiche)
- **Argo Rollouts** · deploy progressivi (canary) con avanzamento controllato

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
├── tasker-deployment-eks.yaml      # Deployment Tasker (alternativa al Rollout)
├── tasker-rollout-argo.yaml        # Rollout Argo (canary) — modo di deploy attuale
├── tasker-hpa.yaml                 # HorizontalPodAutoscaler (target: Rollout)
├── tasker-pdb.yaml                 # PodDisruptionBudget
├── tasker-service-loadbalancer-eks.yaml
├── tasker-serviceaccount.yaml
├── storageclass-gp3.yaml           # StorageClass EBS gp3 default
│
└── .github/workflows/deploy.yaml   # pipeline CI/CD GitHub Actions (canary)
```

**Nota su Deployment vs Rollout**: `tasker-deployment-eks.yaml` (Deployment
classico) e `tasker-rollout-argo.yaml` (Rollout di Argo Rollouts) sono due modi
alternativi di gestire lo stesso workload `tasker` — **non vanno applicati
insieme**. Il modo di deploy attuale è il Rollout (deploy progressivo canary).
Il Deployment resta come riferimento del setup pre-Argo Rollouts.

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

Prerequisito per il Rollout: il controller Argo Rollouts installato nel cluster.

```bash
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts \
  -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
```

Ordine consigliato di apply:

1. `*-serviceaccount.yaml`
2. `storageclass-gp3.yaml`, `postgres-configmap.yaml`
3. `postgres-secretproviderclass.yaml`
4. Database: `postgres-cluster-cnpg.yaml` (richiede il Secret `tasker-db-credentials`)
5. `tasker-rollout-argo.yaml` (Rollout canary) — **oppure** `tasker-deployment-eks.yaml` (Deployment classico)
6. `tasker-pdb.yaml`, `tasker-hpa.yaml`
7. `tasker-service-loadbalancer-eks.yaml`

Avanzamento e controllo del canary:

```bash
kubectl argo rollouts get rollout tasker --watch   # stato live
kubectl argo rollouts promote tasker               # promuovi al passo successivo
kubectl argo rollouts abort tasker                 # rollback alla versione stabile
```

## CI/CD

`.github/workflows/deploy.yaml` builda l'immagine arm64, la pusha su ECR con
tag = SHA del commit, e avvia un deploy canary sul Rollout via
`kubectl argo rollouts set image`. L'autenticazione su AWS avviene via OIDC
federation: nessuna chiave statica nei Secrets di GitHub.

La pipeline porta il canary fino al punto di pausa e verifica che sia sano
(pod canary healthy + smoke test). La **promozione finale al 100% è manuale**
(`kubectl argo rollouts promote tasker`): è una scelta deliberata, l'umano
decide se completare il rilascio dopo aver osservato il canary.

Setup AWS (IAM role OIDC, EKS Access Entry) e materiali editoriali della serie
sono in `~/Repository/personal/BreakingProd-materiali/`.
