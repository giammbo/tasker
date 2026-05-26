"""
Tasker v0.3.0 - API REST per gestione task con persistenza Postgres.

Differenze rispetto alla v0.2.0:
- La password del DB viene letta da file (modo canonico Secrets Store CSI
  Driver), con retry: il volume CSI puo' impiegare qualche centinaio di ms
  a popolarsi dopo l'avvio del container.

Variabili d'ambiente attese (iniettate da ConfigMap + Secrets Store CSI Driver):
- POSTGRES_HOST     (es. postgres-service)
- POSTGRES_PORT     (es. 5432)
- POSTGRES_DB       (es. tasker)
- POSTGRES_USER     (es. tasker)
- POSTGRES_PASSWORD oppure POSTGRES_PASSWORD_FILE

Gestione della password (modo canonico Secrets Store CSI Driver):
La password NON viene da un Secret K8s. Il Secrets Store CSI Driver la monta
come file dentro al pod. Tasker legge il percorso del file dalla variabile
POSTGRES_PASSWORD_FILE e ne legge il contenuto. Se POSTGRES_PASSWORD_FILE non
e' impostata, ricade sulla variabile POSTGRES_PASSWORD (utile in locale).
Questo segue la convenzione "_FILE" usata da Docker, Postgres e altri.

IMPORTANTE: il volume CSI viene montato dal kubelet, ma il provider AWS
impiega qualche centinaio di millisecondi a scrivere i file dentro al volume.
Se l'app legge il file troppo presto, la directory esiste ma e' vuota.
Per questo _file_env() fa un breve retry prima di arrendersi.
"""

import os
import time
from datetime import datetime
from flask import Flask, jsonify, request
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError

app = Flask(__name__)

# ----- Lettura variabili d'ambiente con supporto convenzione _FILE -----

def _file_env(name, default="", max_attempts=30, delay=1):
    """
    Legge una variabile d'ambiente con supporto alla convenzione "_FILE".

    Se esiste <name>_FILE, ne legge il contenuto dal file indicato. Il file
    e' fornito dal Secrets Store CSI Driver come volume montato: puo' non
    essere subito presente all'avvio del container, quindi si fa un retry
    fino a max_attempts (default 30 tentativi a 1s = fino a 30s).

    Se <name>_FILE non e' impostata, usa la variabile <name> diretta.
    Se nessuna delle due e' disponibile, ritorna il default.
    """
    file_path = os.getenv(f"{name}_FILE")
    if file_path:
        for attempt in range(1, max_attempts + 1):
            try:
                with open(file_path, "r") as f:
                    content = f.read().strip()
                if content:
                    print(f"[tasker] secret file {file_path} letto al tentativo {attempt}")
                    return content
                # file presente ma ancora vuoto: il provider non ha finito
                print(f"[tasker] secret file {file_path} ancora vuoto "
                      f"(tentativo {attempt}/{max_attempts})")
            except FileNotFoundError:
                print(f"[tasker] secret file {file_path} non ancora montato "
                      f"(tentativo {attempt}/{max_attempts})")
            time.sleep(delay)
        raise RuntimeError(
            f"secret file {file_path} non disponibile dopo {max_attempts} tentativi"
        )
    return os.getenv(name, default)


# ----- Configurazione DB da variabili d'ambiente -----

def build_db_url():
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "tasker")
    user = os.getenv("POSTGRES_USER", "tasker")
    # La password puo' arrivare da file (POSTGRES_PASSWORD_FILE, montato da
    # SSCD, con retry) oppure da variabile diretta (POSTGRES_PASSWORD, locale).
    password = _file_env("POSTGRES_PASSWORD", "")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL = build_db_url()
Base = declarative_base()


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(String(1000), default="")
    done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description or "",
            "done": self.done,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else None,
        }


# ----- Connessione con retry -----

def wait_for_db(max_attempts=30, delay=2):
    """Aspetta che Postgres sia raggiungibile prima di partire."""
    for attempt in range(1, max_attempts + 1):
        try:
            engine = create_engine(DATABASE_URL, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"[tasker] connected to database on attempt {attempt}")
            return engine
        except OperationalError as e:
            print(f"[tasker] db not ready (attempt {attempt}/{max_attempts}): {e}")
            time.sleep(delay)
    raise RuntimeError("could not connect to database after retries")


engine = wait_for_db()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base.metadata.create_all(engine)
print("[tasker] tasks table ensured")


# ----- Helper -----

def get_session():
    return SessionLocal()


# ----- Endpoint -----

@app.route("/health", methods=["GET"])
def health():
    """Health check. Verifica anche la connessione al DB."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    status = "ok" if db_ok else "degraded"
    return jsonify({
        "status": status,
        "service": "tasker",
        "version": os.getenv("APP_VERSION", "0.3.0"),
        "hostname": os.getenv("HOSTNAME", "unknown"),
        "db": "ok" if db_ok else "unavailable",
    }), 200 if db_ok else 503


@app.route("/tasks", methods=["GET"])
def list_tasks():
    session = get_session()
    try:
        rows = session.query(Task).order_by(Task.id).all()
        return jsonify({
            "tasks": [t.to_dict() for t in rows],
            "count": len(rows),
        }), 200
    finally:
        session.close()


@app.route("/tasks", methods=["POST"])
def create_task():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    session = get_session()
    try:
        task = Task(
            title=title,
            description=data.get("description", ""),
            done=False,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return jsonify(task.to_dict()), 201
    finally:
        session.close()


@app.route("/tasks/<int:task_id>", methods=["GET"])
def get_task(task_id):
    session = get_session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if task is None:
            return jsonify({"error": "task not found"}), 404
        return jsonify(task.to_dict()), 200
    finally:
        session.close()


@app.route("/tasks/<int:task_id>", methods=["PATCH"])
def update_task(task_id):
    data = request.get_json(silent=True) or {}
    session = get_session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if task is None:
            return jsonify({"error": "task not found"}), 404

        if "done" in data:
            task.done = bool(data["done"])
        if "title" in data:
            task.title = str(data["title"]).strip()
        if "description" in data:
            task.description = str(data["description"])

        session.commit()
        session.refresh(task)
        return jsonify(task.to_dict()), 200
    finally:
        session.close()


@app.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    session = get_session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        if task is None:
            return jsonify({"error": "task not found"}), 404
        session.delete(task)
        session.commit()
        return "", 204
    finally:
        session.close()


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "tasker",
        "version": "0.3.0",
        "message": "Tasker con persistenza Postgres",
        "endpoints": {
            "GET /health": "health check (include stato DB)",
            "GET /tasks": "list all tasks",
            "POST /tasks": "create a task",
            "GET /tasks/<id>": "get a single task",
            "PATCH /tasks/<id>": "update a task",
            "DELETE /tasks/<id>": "delete a task",
        },
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
