import os
from typing import Optional
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
START_DATE = os.getenv("BOT_START_DATE")

# Usar make_url para evitar bugs de string manipulation y forzar driver pg8000
_engine = create_engine(make_url(DATABASE_URL).set(drivername="postgresql+pg8000"))


def query_df(sql: str, params: Optional[dict] = None) -> pd.DataFrame:
    with _engine.connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


def _country_clause(alias: str = "") -> str:
    col = f"{alias}.client_number" if alias else "client_number"
    return f"AND {col} ~ '^(57|59)'"


def _city_subq() -> str:
    return (
        "AND client_number IN "
        "(SELECT DISTINCT client_number FROM ama.ama_user_info_table_v1 WHERE city = :city)"
    )


# ── Ciudades disponibles ──────────────────────────────────────────────────────

def get_cities() -> list:
    rows = query_df("""
        SELECT DISTINCT u.city
        FROM ama.ama_user_info_table_v1 u
        WHERE u.city IS NOT NULL AND u.city <> ''
          AND u.client_number IN (
              SELECT DISTINCT client_number
              FROM ama.ama_session_start_table
              WHERE DATE(created_at AT TIME ZONE 'America/Bogota') >= :start
                AND client_number ~ '^(57|59)'
          )
        ORDER BY u.city
    """, {"start": START_DATE})
    return rows["city"].tolist()


# ── Overview ─────────────────────────────────────────────────────────────────

def get_kpis(city: Optional[str] = None) -> dict:
    if city:
        cq = ("AND client_number IN "
              "(SELECT DISTINCT client_number FROM ama.ama_user_info_table_v1 WHERE city = %(city)s)")
        params = {"city": city, "start": START_DATE}
    else:
        cq = ""
        params = {"start": START_DATE}

    # Rewrite usando named params para query_df (SQLAlchemy text)
    cq_named = cq.replace("%(city)s", ":city").replace("%(start)s", ":start")
    sql = f"""
        SELECT
            (SELECT COUNT(DISTINCT s.client_number)
               FROM ama.ama_session_start_table s
              WHERE DATE(s.created_at AT TIME ZONE 'America/Bogota') >= :start {cq_named})  AS total_usuarios,

            (SELECT COUNT(*)
               FROM ama.ama_session_start_table s
              WHERE DATE(s.created_at AT TIME ZONE 'America/Bogota') >= :start {cq_named})  AS total_inicios,

            (SELECT COUNT(DISTINCT r.client_number)
               FROM ama.ama_sessions_responses r
              WHERE DATE(r.created_at AT TIME ZONE 'America/Bogota') >= :start {cq_named})  AS usuarios_con_resp,

            (SELECT COUNT(DISTINCT s.client_number)
               FROM ama.ama_session_start_table s
              WHERE s.created_at >= NOW() - INTERVAL '7 days' {cq_named})                  AS activos_7d
    """
    row = query_df(sql, params)
    return row.iloc[0].to_dict()


# ── Actividad por día ─────────────────────────────────────────────────────────

def get_daily_activity(city: Optional[str] = None) -> pd.DataFrame:
    city_clause = _city_subq() if city else ""
    sql = f"""
        SELECT
            DATE(created_at AT TIME ZONE 'America/Bogota') AS fecha,
            COUNT(*) AS inicios_sesion
        FROM ama.ama_session_start_table
        WHERE DATE(created_at AT TIME ZONE 'America/Bogota') >= :start
          {_country_clause()}
          {city_clause}
        GROUP BY 1 ORDER BY 1
    """
    params = {"start": START_DATE}
    if city:
        params["city"] = city
    return query_df(sql, params)


def get_sessions_by_session_day(city: Optional[str] = None) -> pd.DataFrame:
    city_clause = _city_subq() if city else ""
    sql = f"""
        SELECT
            session,
            day,
            COUNT(DISTINCT client_number) AS usuarios
        FROM ama.ama_session_start_table
        WHERE DATE(created_at AT TIME ZONE 'America/Bogota') >= :start
          {_country_clause()}
          {city_clause}
        GROUP BY session, day
        ORDER BY session::int, day::int
    """
    params = {"start": START_DATE}
    if city:
        params["city"] = city
    return query_df(sql, params)


def get_responses_by_session_day(city: Optional[str] = None) -> pd.DataFrame:
    city_clause = _city_subq() if city else ""
    sql = f"""
        SELECT
            session,
            day,
            COUNT(DISTINCT client_number) AS usuarios_con_respuesta
        FROM ama.ama_sessions_responses
        WHERE DATE(created_at AT TIME ZONE 'America/Bogota') >= :start
          {_country_clause()}
          {city_clause}
        GROUP BY session, day
        ORDER BY session::int, day::int
    """
    params = {"start": START_DATE}
    if city:
        params["city"] = city
    return query_df(sql, params)


# ── Funnel de completación ────────────────────────────────────────────────────

def get_funnel(city: Optional[str] = None) -> pd.DataFrame:
    if city:
        cq = ("AND client_number IN "
              "(SELECT DISTINCT client_number FROM ama.ama_user_info_table_v1 WHERE city = :city)")
        params = {"city": city, "start": START_DATE}
    else:
        cq = ""
        params = {"start": START_DATE}

    sql = f"""
        SELECT 'Registrados'         AS etapa, 1 AS orden,
               COUNT(DISTINCT client_number) AS usuarios
        FROM ama.ama_user_info_table_v1
        WHERE DATE(created_at AT TIME ZONE 'America/Bogota') >= :start
          {cq.replace('AND client_number IN', 'AND client_number IN') if cq else ''}

        UNION ALL

        SELECT 'Iniciaron sesión'    AS etapa, 2,
               COUNT(DISTINCT client_number)
        FROM ama.ama_session_start_table
        WHERE DATE(created_at AT TIME ZONE 'America/Bogota') >= :start
          {cq}

        UNION ALL

        SELECT 'Enviaron respuestas' AS etapa, 3,
               COUNT(DISTINCT client_number)
        FROM ama.ama_sessions_responses
        WHERE DATE(created_at AT TIME ZONE 'America/Bogota') >= :start
          {cq}

        ORDER BY orden
    """
    return query_df(sql, params)


# ── Demografía — solo usuarios con sesión desde START_DATE ───────────────────

def _active_users_cte(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    school: Optional[str] = None,
) -> tuple:
    """
    Retorna (cte_sql, params) con los usuarios activos en el rango de fechas,
    deduplicados con su registro más reciente.
    """
    df = date_from or START_DATE
    dt = date_to or "9999-12-31"
    city_clause = "AND u.city = :city" if city else ""
    school_clause = "AND u.school = :school" if school else ""
    cte = f"""
        WITH active_clients AS (
            SELECT DISTINCT client_number
            FROM ama.ama_session_start_table
            WHERE DATE(created_at AT TIME ZONE 'America/Bogota') BETWEEN :date_from AND :date_to
              AND client_number ~ '^(57|59)'
        ),
        latest AS (
            SELECT DISTINCT ON (u.client_number)
                u.client_number, u.name, u.gender, u.age,
                u.course, u.school, u.city, u.created_at
            FROM ama.ama_user_info_table_v1 u
            INNER JOIN active_clients ac USING (client_number)
            WHERE TRUE {city_clause} {school_clause}
            ORDER BY u.client_number, u.created_at DESC
        )
    """
    params: dict = {"date_from": df, "date_to": dt}
    if city:
        params["city"] = city
    if school:
        params["school"] = school
    return cte, params


def get_users_count(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    school: Optional[str] = None,
) -> int:
    cte, params = _active_users_cte(city, date_from, date_to, school)
    df = query_df(cte + "SELECT COUNT(*) AS n FROM latest", params)
    return int(df["n"].iloc[0])


def get_gender_dist(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    school: Optional[str] = None,
) -> pd.DataFrame:
    cte, params = _active_users_cte(city, date_from, date_to, school)
    return query_df(cte + """
        SELECT COALESCE(gender, 'Sin registrar') AS gender, COUNT(*) AS cantidad
        FROM latest
        GROUP BY gender ORDER BY cantidad DESC
    """, params)


def get_school_dist(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> pd.DataFrame:
    cte, params = _active_users_cte(city, date_from, date_to)
    return query_df(cte + """
        SELECT COALESCE(school, 'Sin registrar') AS school, COUNT(*) AS cantidad
        FROM latest
        GROUP BY school ORDER BY cantidad DESC
    """, params)


def get_city_dist() -> pd.DataFrame:
    cte, params = _active_users_cte()
    return query_df(cte + """
        SELECT COALESCE(city, 'Sin registrar') AS city, COUNT(*) AS cantidad
        FROM latest
        GROUP BY city ORDER BY cantidad DESC
    """, params)


def get_daily_users_by_gender(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    school: Optional[str] = None,
) -> pd.DataFrame:
    df = date_from or START_DATE
    dt = date_to or "9999-12-31"
    city_clause = "AND u.city = :city" if city else ""
    school_clause = "AND u.school = :school" if school else ""
    sql = f"""
        SELECT
            DATE(s.created_at AT TIME ZONE 'America/Bogota')::text AS fecha,
            COALESCE(u.gender, 'Sin registrar') AS gender,
            COUNT(DISTINCT s.client_number) AS usuarios
        FROM ama.ama_session_start_table s
        LEFT JOIN ama.ama_user_info_table_v1 u USING (client_number)
        WHERE DATE(s.created_at AT TIME ZONE 'America/Bogota') BETWEEN :date_from AND :date_to
          {_country_clause("s")}
          {city_clause}
          {school_clause}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    params: dict = {"date_from": df, "date_to": dt}
    if city:
        params["city"] = city
    if school:
        params["school"] = school
    return query_df(sql, params)


def get_users_by_session_and_gender(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    school: Optional[str] = None,
) -> pd.DataFrame:
    df = date_from or START_DATE
    dt = date_to or "9999-12-31"
    city_clause = "AND u.city = :city" if city else ""
    school_clause = "AND u.school = :school" if school else ""
    sql = f"""
        SELECT
            s.session::int AS sesion,
            COALESCE(u.gender, 'Sin registrar') AS gender,
            COUNT(DISTINCT s.client_number) AS usuarios
        FROM ama.ama_session_start_table s
        LEFT JOIN ama.ama_user_info_table_v1 u USING (client_number)
        WHERE DATE(s.created_at AT TIME ZONE 'America/Bogota') BETWEEN :date_from AND :date_to
          {_country_clause("s")}
          {city_clause}
          {school_clause}
        GROUP BY sesion, gender
        ORDER BY sesion, gender
    """
    params: dict = {"date_from": df, "date_to": dt}
    if city:
        params["city"] = city
    if school:
        params["school"] = school
    return query_df(sql, params)


def get_schools(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list:
    df = date_from or START_DATE
    dt = date_to or "9999-12-31"
    city_clause = "AND u.city = :city" if city else ""
    sql = f"""
        SELECT DISTINCT COALESCE(u.school, 'Sin registrar') AS school
        FROM ama.ama_session_start_table s
        LEFT JOIN ama.ama_user_info_table_v1 u USING (client_number)
        WHERE DATE(s.created_at AT TIME ZONE 'America/Bogota') BETWEEN :date_from AND :date_to
          {_country_clause("s")}
          {city_clause}
          AND u.school IS NOT NULL AND u.school <> ''
        ORDER BY school
    """
    params: dict = {"date_from": df, "date_to": dt}
    if city:
        params["city"] = city
    return query_df(sql, params)["school"].tolist()


def get_daily_users_by_school(
    schools: list,
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> pd.DataFrame:
    df = date_from or START_DATE
    dt = date_to or "9999-12-31"
    city_clause = "AND u.city = :city" if city else ""
    sql = f"""
        SELECT
            DATE(s.created_at AT TIME ZONE 'America/Bogota')::text AS fecha,
            COALESCE(u.school, 'Sin registrar') AS school,
            COALESCE(u.gender, 'Sin registrar') AS gender,
            COUNT(DISTINCT s.client_number) AS usuarios
        FROM ama.ama_session_start_table s
        LEFT JOIN ama.ama_user_info_table_v1 u USING (client_number)
        WHERE DATE(s.created_at AT TIME ZONE 'America/Bogota') BETWEEN :date_from AND :date_to
          {_country_clause("s")}
          {city_clause}
          AND u.school = ANY(:schools)
        GROUP BY fecha, school, gender
        ORDER BY fecha, school, gender
    """
    params: dict = {"date_from": df, "date_to": dt, "schools": schools}
    if city:
        params["city"] = city
    return query_df(sql, params)


def get_school_session_dist(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> pd.DataFrame:
    """Usuarios únicos por colegio × sesión máxima alcanzada en el rango."""
    df = date_from or START_DATE
    dt = date_to or "9999-12-31"
    city_clause = "AND u.city = :city" if city else ""
    sql = f"""
        WITH max_session AS (
            SELECT
                s.client_number,
                MAX(s.session::int) AS max_sesion
            FROM ama.ama_session_start_table s
            WHERE DATE(s.created_at AT TIME ZONE 'America/Bogota') BETWEEN :date_from AND :date_to
              {_country_clause("s")}
            GROUP BY s.client_number
        )
        SELECT
            COALESCE(u.school, 'Sin registrar') AS school,
            ms.max_sesion AS sesion,
            COUNT(*) AS usuarios
        FROM max_session ms
        LEFT JOIN ama.ama_user_info_table_v1 u USING (client_number)
        WHERE TRUE {city_clause}
        GROUP BY school, sesion
        ORDER BY school, sesion
    """
    params: dict = {"date_from": df, "date_to": dt}
    if city:
        params["city"] = city
    return query_df(sql, params)


def get_users_by_session(
    city: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> pd.DataFrame:
    df = date_from or START_DATE
    dt = date_to or "9999-12-31"
    city_clause = _city_subq() if city else ""
    sql = f"""
        SELECT session::int AS sesion, COUNT(DISTINCT client_number) AS usuarios
        FROM ama.ama_session_start_table
        WHERE DATE(created_at AT TIME ZONE 'America/Bogota') BETWEEN :date_from AND :date_to
          {_country_clause()}
          {city_clause}
        GROUP BY session::int
        ORDER BY session::int
    """
    params: dict = {"date_from": df, "date_to": dt}
    if city:
        params["city"] = city
    return query_df(sql, params)


def get_users(city: Optional[str] = None) -> pd.DataFrame:
    cte, params = _active_users_cte(city, START_DATE)
    sql = cte + """
        SELECT
            l.name,
            l.gender,
            l.age,
            l.course,
            l.school,
            l.city,
            l.client_number,
            l.created_at AT TIME ZONE 'America/Bogota' AS registered_at,
            COUNT(DISTINCT s.session || '-' || s.day) AS sesiones_iniciadas,
            COUNT(DISTINCT r.id)                       AS respuestas_enviadas
        FROM latest l
        LEFT JOIN ama.ama_session_start_table s
               ON s.client_number = l.client_number
              AND DATE(s.created_at AT TIME ZONE 'America/Bogota') >= :date_from
        LEFT JOIN ama.ama_sessions_responses r
               ON r.client_number = l.client_number
              AND DATE(r.created_at AT TIME ZONE 'America/Bogota') >= :date_from
        GROUP BY l.name, l.gender, l.age, l.course, l.school,
                 l.city, l.client_number, registered_at
        ORDER BY registered_at DESC
    """
    return query_df(sql, params)


# ── Reporte semanal ───────────────────────────────────────────────────────────

def get_usage_by_dimension(dimension_col: str, fecha_inicio: str, fecha_fin: str) -> pd.DataFrame:
    sql = f"""
        SELECT
            DATE(s.created_at AT TIME ZONE 'America/Bogota') AS fecha,
            COALESCE(u.{dimension_col}, 'Sin registrar')     AS dimension,
            COALESCE(u.gender, 'Sin registrar')              AS gender,
            COUNT(DISTINCT s.client_number)                  AS usuarios
        FROM ama.ama_session_start_table s
        LEFT JOIN ama.ama_user_info_table_v1 u USING (client_number)
        WHERE DATE(s.created_at AT TIME ZONE 'America/Bogota')
              BETWEEN :fecha_inicio AND :fecha_fin
          AND s.client_number ~ '^(57|59)'
        GROUP BY fecha, dimension, gender
        ORDER BY fecha, dimension, gender
    """
    return query_df(sql, params={"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin})


# ── Respuestas ────────────────────────────────────────────────────────────────

def get_available_sessions(city: Optional[str] = None) -> list:
    city_clause = _city_subq() if city else ""
    sql = f"""
        SELECT session, day
        FROM ama.ama_sessions_responses
        WHERE DATE(created_at AT TIME ZONE 'America/Bogota') >= :start
          {_country_clause()}
          {city_clause}
        GROUP BY session, day
        ORDER BY session::int, day::int
    """
    params = {"start": START_DATE}
    if city:
        params["city"] = city
    return query_df(sql, params).to_dict("records")


def get_responses(session: str, day: str, city: Optional[str] = None) -> pd.DataFrame:
    city_clause = "AND u.city = :city" if city else ""
    sql = f"""
        SELECT
            u.name,
            u.school,
            u.course,
            u.gender,
            r.responses,
            r.created_at AT TIME ZONE 'America/Bogota' AS respondido_at
        FROM ama.ama_sessions_responses r
        LEFT JOIN ama.ama_user_info_table_v1 u USING (client_number)
        WHERE r.session = :session AND r.day = :day
          AND DATE(r.created_at AT TIME ZONE 'America/Bogota') >= :start
          AND r.client_number ~ '^(57|59)'
          {city_clause}
        ORDER BY respondido_at
    """
    params = {"session": session, "day": day, "start": START_DATE}
    if city:
        params["city"] = city
    return query_df(sql, params)
