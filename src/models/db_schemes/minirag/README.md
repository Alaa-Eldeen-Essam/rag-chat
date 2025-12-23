## Run Alembic Migrations

### Configuration

```bash
cp alembic.ini.example alembic.ini
```

- Update the `alembic.ini` with your database credentials (`sqlalchemy.url`)
  
### (Optional) Create a new migration

```bash
alembic revision --autogenerate -m "Add ..."
```

Use a descriptive message (for example, when you add new fields to `ChatHistory` for feedback and retrieval metadata, or change visibility columns on `Asset`):

```bash
alembic revision --autogenerate -m "Add feedback & retrieval fields to ChatHistory"
```

### Upgrade the database

```bash
alembic upgrade head
```

> Whenever you change any SQLAlchemy models in `src/models/db_schemes/minirag/schemes/`, create a new revision and upgrade so that the DB schema stays in sync with the code.
