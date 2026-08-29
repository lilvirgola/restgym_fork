import os
import sqlite3

from mitmproxy import ctx


class StoreInteractions:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.count = 0

        ctx.log.info("StoreInteractions: initializing")

        try:
            self.conn = self.open_sqlite()
            self.cursor = self.conn.cursor()
            self.init_sqlite()
            ctx.log.info("StoreInteractions: initialized successfully")
        except Exception as e:
            ctx.log.error(f"StoreInteractions: initialization failed: {e}")
            raise

    def open_sqlite(self):
        api = os.environ.get("API", "default")
        tool = os.environ.get("TOOL", "default")
        run = os.environ.get("RUN", "default")

        db_path = (
            f"/results/{api}/{tool}/{run}/results.db"
        )

        ctx.log.info(f"Opening SQLite database: {db_path}")

        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            conn = sqlite3.connect(db_path)
            ctx.log.info("SQLite connection established")
            return conn
        except Exception as e:
            ctx.log.error(
                f"Failed to open SQLite database {db_path}: {e}"
            )
            raise

    def init_sqlite(self):
        ctx.log.info("Initializing SQLite schema")

        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY,
                    request_method TEXT,
                    request_path TEXT,
                    request_headers TEXT,
                    request_content TEXT,
                    request_timestamp REAL,

                    response_status_code INTEGER,
                    response_headers TEXT,
                    response_content TEXT,
                    response_timestamp REAL,

                    mutant_id TEXT,
                    mutant_operator TEXT,
                    mutant_taxonomy TEXT,
                    is_killed INTEGER
                )
            """)

            self.conn.commit()

            ctx.log.info("SQLite schema initialized")
        except Exception as e:
            ctx.log.error(f"Failed to initialize SQLite schema: {e}")
            raise

    def response(self, flow):
        ctx.log.info(
            f"Processing response: "
            f"{flow.request.method} {flow.request.path}"
        )

        try:
            # --- Mutant information ---
            metadata = getattr(flow, "metadata", {})

            ctx.log.info(
                f"Flow metadata type={type(metadata).__name__}, "
                f"value={metadata!r}"
            )

            mutant = metadata.get("active_mutant")

            ctx.log.info(
                f"Active mutant type={type(mutant).__name__}, "
                f"value={mutant!r}"
            )

            if isinstance(mutant, dict):
                m_id = mutant.get("id")
                m_op = mutant.get("operator")
                m_tax = mutant.get("taxonomy")
            else:
                m_id = None
                m_op = None
                m_tax = None

            ctx.log.info(
                f"Mutant data: id={m_id!r}, "
                f"operator={m_op!r}, taxonomy={m_tax!r}"
            )

            # --- Request ---
            req_headers = "\r\n".join(
                f"{k}: {v}"
                for k, v in flow.request.headers.items()
            )

            req_content = (
                flow.request.content.decode(
                    "utf-8",
                    errors="replace",
                )
                if flow.request.content
                else ""
            )

            # --- Response ---
            res_headers = ""
            res_content = ""
            res_status = None
            res_time = None

            if flow.response is not None:
                res_headers = "\r\n".join(
                    f"{k}: {v}"
                    for k, v in flow.response.headers.items()
                )

                res_content = (
                    flow.response.content.decode(
                        "utf-8",
                        errors="replace",
                    )
                    if flow.response.content
                    else ""
                )

                res_status = flow.response.status_code
                res_time = flow.response.timestamp_start

            ctx.log.info(
                f"Response status={res_status}, "
                f"request_content_length={len(req_content)}, "
                f"response_content_length={len(res_content)}"
            )

            # --- Database ---
            ctx.log.info("Inserting interaction into SQLite")

            self.cursor.execute("""
                INSERT INTO interactions (
                    request_method,
                    request_path,
                    request_headers,
                    request_content,
                    request_timestamp,

                    response_status_code,
                    response_headers,
                    response_content,
                    response_timestamp,

                    mutant_id,
                    mutant_operator,
                    mutant_taxonomy
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                flow.request.method,
                flow.request.path,
                req_headers,
                req_content,
                flow.request.timestamp_start,

                res_status,
                res_headers,
                res_content,
                res_time,

                m_id,
                m_op,
                m_tax,
            ))

            self.count += 1

            ctx.log.info(
                f"Interaction inserted successfully "
                f"(count={self.count})"
            )

            if self.count % 100 == 0:
                ctx.log.info("Committing SQLite transaction")
                self.conn.commit()
                ctx.log.info("SQLite commit successful")

        except Exception as e:
            ctx.log.error(
                f"Failed processing interaction: "
                f"{flow.request.method} {flow.request.path}: {e}"
            )

            # This logs the full traceback in mitmproxy.
            ctx.log.error(
                "Interaction processing exception",
                exc_info=True,
            )

    def done(self):
        ctx.log.info("StoreInteractions: shutting down")

        try:
            if self.conn:
                ctx.log.info("Committing final SQLite transaction")
                self.conn.commit()

                ctx.log.info("Closing SQLite connection")
                self.conn.close()

                ctx.log.info("StoreInteractions: shutdown complete")

        except Exception as e:
            ctx.log.error(
                f"Failed during StoreInteractions shutdown: {e}",
                exc_info=True,
            )


addons = [StoreInteractions()]