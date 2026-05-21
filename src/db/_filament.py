import sqlite3

from ._connection import DatabaseError


def insert_spool(conn: sqlite3.Connection, spool: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO filament_spool
          (uid, material, color_name, color_hex, initial_weight_g,
           price, purchased_at, product_url, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            spool["uid"],
            spool.get("material"),
            spool.get("color_name"),
            spool.get("color_hex"),
            spool["initial_weight_g"],
            spool.get("price"),
            spool.get("purchased_at"),
            spool.get("product_url"),
            spool.get("note"),
        ),
    )
    return cursor.lastrowid


def update_spool(conn: sqlite3.Connection, spool_id: int, spool: dict) -> None:
    conn.execute(
        """
        UPDATE filament_spool SET
          material=?, color_name=?, color_hex=?, initial_weight_g=?,
          price=?, purchased_at=?, product_url=?, note=?
        WHERE id=?
        """,
        (
            spool.get("material"),
            spool.get("color_name"),
            spool.get("color_hex"),
            spool["initial_weight_g"],
            spool.get("price"),
            spool.get("purchased_at"),
            spool.get("product_url"),
            spool.get("note"),
            spool_id,
        ),
    )


def delete_spool(conn: sqlite3.Connection, spool_id: int) -> None:
    conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=NULL WHERE filament_spool_id=?",
        (spool_id,),
    )
    conn.execute("DELETE FROM filament_spool WHERE id=?", (spool_id,))


def get_all_spools(conn: sqlite3.Connection) -> list:
    return conn.execute("SELECT * FROM filament_spool ORDER BY id").fetchall()


def get_spool_by_id(conn: sqlite3.Connection, spool_id: int):
    return conn.execute(
        "SELECT * FROM filament_spool WHERE id=?", (spool_id,)
    ).fetchone()


def get_spool_used_weight(conn: sqlite3.Connection, spool_id: int) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(used_weight_g), 0.0) AS total
        FROM print_task_filament
        WHERE filament_spool_id=?
        """,
        (spool_id,),
    ).fetchone()
    return row["total"]


def get_unmapped_filaments(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          pt.print_name, pt.started_at, pt.external_id, pt.cover_url,
          pt.status, pt.is_manual
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        WHERE ptf.filament_spool_id IS NULL AND ptf.is_ignored = 0
        ORDER BY pt.started_at DESC
        """
    ).fetchall()


def get_ignored_filaments(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          pt.print_name, pt.started_at, pt.external_id, pt.cover_url,
          pt.status, pt.is_manual
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        WHERE ptf.filament_spool_id IS NULL AND ptf.is_ignored = 1
        ORDER BY pt.started_at DESC
        """
    ).fetchall()


def ignore_filament(conn: sqlite3.Connection, ptf_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET is_ignored=1 WHERE id=? AND filament_spool_id IS NULL AND is_ignored=0",
        (ptf_id,),
    )
    if cursor.rowcount == 0:
        raise DatabaseError(f"print_task_filament id={ptf_id} 不存在、已對照或已忽略。")


def unignore_filament(conn: sqlite3.Connection, ptf_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET is_ignored=0 WHERE id=? AND is_ignored=1",
        (ptf_id,),
    )
    if cursor.rowcount == 0:
        raise DatabaseError(f"print_task_filament id={ptf_id} 不存在或未被忽略。")


def get_ptf_by_id(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        "SELECT id FROM print_task_filament WHERE id=?", (ptf_id,)
    ).fetchone()


def get_ptf_row_with_spool(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        """
        SELECT ptf.id, ptf.slot_id, ptf.material, ptf.color_hex,
               ptf.used_weight_g, ptf.filament_spool_id,
               fs.color_name
        FROM print_task_filament ptf
        LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.id = ?
        """,
        (ptf_id,),
    ).fetchone()


def get_ptf_material(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        "SELECT material FROM print_task_filament WHERE id=?", (ptf_id,)
    ).fetchone()


def get_spool_last_used_map(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT filament_spool_id, MAX(mapped_at) AS last_used_at
        FROM print_task_filament
        WHERE filament_spool_id IS NOT NULL AND mapped_at IS NOT NULL
        GROUP BY filament_spool_id
        """
    ).fetchall()
    return {r["filament_spool_id"]: r["last_used_at"] for r in rows}


def get_mapped_filaments(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          ptf.filament_spool_id,
          pt.print_name, pt.started_at, pt.cover_url,
          pt.status, pt.is_manual,
          fs.color_name AS spool_color_name,
          fs.color_hex AS spool_color_hex,
          fs.material AS spool_material,
          fs.initial_weight_g AS spool_initial_weight_g
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.filament_spool_id IS NOT NULL
        ORDER BY pt.started_at DESC
        """
    ).fetchall()


def update_ptf_material(conn: sqlite3.Connection, ptf_id: int, material) -> int:
    cursor = conn.execute(
        "UPDATE print_task_filament SET material=? WHERE id=? AND filament_spool_id IS NULL",
        (material, ptf_id),
    )
    return cursor.rowcount


def get_mapped_filament_by_id(conn: sqlite3.Connection, ptf_id: int):
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.print_task_id, ptf.slot_id,
          ptf.used_weight_g, ptf.color_hex, ptf.material,
          ptf.filament_spool_id,
          pt.print_name, pt.started_at, pt.cover_url,
          pt.status, pt.is_manual,
          fs.color_name AS spool_color_name,
          fs.color_hex AS spool_color_hex,
          fs.material AS spool_material
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.id = ? AND ptf.filament_spool_id IS NOT NULL
        """,
        (ptf_id,),
    ).fetchone()


def unmap_filament(conn: sqlite3.Connection, ptf_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=NULL WHERE id=? AND filament_spool_id IS NOT NULL",
        (ptf_id,),
    )
    if cursor.rowcount == 0:
        raise DatabaseError(f"print_task_filament id={ptf_id} 不存在或已是未對照狀態。")


def map_filament_to_spool(conn: sqlite3.Connection, ptf_id: int, spool_id: int) -> None:
    cursor = conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=?, is_ignored=0, mapped_at=CURRENT_TIMESTAMP WHERE id=?",
        (spool_id, ptf_id),
    )
    if cursor.rowcount == 0:
        raise DatabaseError(f"print_task_filament id={ptf_id} 不存在或更新失敗。")


def get_all_mappings_for_export(conn: sqlite3.Connection) -> list:
    """Fetch all mapped/ignored ptf records using stable cross-system identifiers."""
    return conn.execute(
        """
        SELECT
          ptf.id, ptf.slot_id, ptf.is_ignored, ptf.mapped_at,
          ptf.color_hex, ptf.material, ptf.used_weight_g,
          pt.external_id AS print_task_external_id,
          fs.uid AS spool_uid
        FROM print_task_filament ptf
        JOIN print_task pt ON pt.id = ptf.print_task_id
        LEFT JOIN filament_spool fs ON fs.id = ptf.filament_spool_id
        WHERE ptf.filament_spool_id IS NOT NULL OR ptf.is_ignored = 1
        ORDER BY pt.external_id, ptf.slot_id, ptf.color_hex, ptf.material, ptf.used_weight_g, ptf.id
        """
    ).fetchall()


def get_task_id_by_external_id(conn: sqlite3.Connection, external_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM print_task WHERE external_id = ?", (external_id,)
    ).fetchone()
    return row["id"] if row else None


def get_spool_id_by_uid(conn: sqlite3.Connection, uid: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM filament_spool WHERE uid = ?", (uid,)
    ).fetchone()
    return row["id"] if row else None


def get_ptf_row_by_task_and_slot(conn: sqlite3.Connection, print_task_id: int, slot_id) -> sqlite3.Row | None:
    if slot_id is None:
        # Fallback case: empty amsDetailMapping creates exactly one ptf with slot_id NULL
        return conn.execute(
            "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
            "WHERE print_task_id = ? AND slot_id IS NULL LIMIT 1",
            (print_task_id,),
        ).fetchone()
    return conn.execute(
        "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
        "WHERE print_task_id = ? AND slot_id = ? LIMIT 1",
        (print_task_id, slot_id),
    ).fetchone()


def get_ptf_row_for_mapping(conn: sqlite3.Connection, print_task_id: int, mapping: dict) -> sqlite3.Row | None:
    slot_id = mapping.get("slot_id")
    color_hex = mapping.get("color_hex")
    material = mapping.get("material")
    used_weight_g = mapping.get("used_weight_g")

    if color_hex is not None or material is not None or used_weight_g is not None:
        clauses = ["print_task_id = ?"]
        params: list = [print_task_id]
        if slot_id is None:
            clauses.append("slot_id IS NULL")
        else:
            clauses.append("slot_id = ?")
            params.append(slot_id)
        if color_hex is None:
            clauses.append("color_hex IS NULL")
        else:
            clauses.append("color_hex = ?")
            params.append(color_hex)
        if material is None:
            clauses.append("material IS NULL")
        else:
            clauses.append("material = ?")
            params.append(material)
        if used_weight_g is not None:
            clauses.append("ABS(COALESCE(used_weight_g, 0) - ?) < 0.01")
            params.append(float(used_weight_g))

        matches = conn.execute(
            "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
            f"WHERE {' AND '.join(clauses)} ORDER BY id",
            params,
        ).fetchall()
        occurrence = mapping.get("occurrence_index")
        if occurrence is not None:
            try:
                idx = int(occurrence)
            except (TypeError, ValueError):
                return None
            return matches[idx] if 0 <= idx < len(matches) else None
        return matches[0] if len(matches) == 1 else None

    if slot_id is None:
        rows = conn.execute(
            "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
            "WHERE print_task_id = ? AND slot_id IS NULL",
            (print_task_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, filament_spool_id, is_ignored FROM print_task_filament "
            "WHERE print_task_id = ? AND slot_id = ?",
            (print_task_id, slot_id),
        ).fetchall()
    return rows[0] if len(rows) == 1 else None


def set_ptf_ignored(conn: sqlite3.Connection, ptf_id: int) -> None:
    """Force-set ptf to ignored state, clearing any existing spool mapping."""
    conn.execute(
        "UPDATE print_task_filament SET filament_spool_id=NULL, is_ignored=1, mapped_at=NULL WHERE id=?",
        (ptf_id,),
    )


def get_tasks_grouped_by_spool(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        """
        SELECT
          pt.id, pt.print_name, pt.started_at, pt.cover_url,
          pt.status, pt.is_manual,
          SUM(ptf.used_weight_g) AS used_weight_g,
          ptf.filament_spool_id
        FROM print_task pt
        JOIN print_task_filament ptf ON ptf.print_task_id = pt.id
        WHERE ptf.filament_spool_id IS NOT NULL
        GROUP BY ptf.filament_spool_id, pt.id
        ORDER BY ptf.filament_spool_id, pt.started_at DESC
        """
    ).fetchall()
    result: dict = {}
    for r in rows:
        sid = r["filament_spool_id"]
        if sid not in result:
            result[sid] = []
        result[sid].append(dict(r))
    return result


def get_tasks_for_spool(conn: sqlite3.Connection, spool_id: int) -> list:
    rows = conn.execute(
        """
        SELECT
          pt.id, pt.print_name, pt.started_at, pt.cover_url,
          pt.status, pt.is_manual,
          SUM(ptf.used_weight_g) AS used_weight_g
        FROM print_task pt
        JOIN print_task_filament ptf ON ptf.print_task_id = pt.id
        WHERE ptf.filament_spool_id = ?
        GROUP BY pt.id
        ORDER BY pt.started_at DESC
        """,
        (spool_id,),
    ).fetchall()
    return [dict(r) for r in rows]
