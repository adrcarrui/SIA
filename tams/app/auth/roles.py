# app/auth/roles.py

ALL_ROLES = ["admin", "supervisor", "employee", "user"]

def get_assignable_roles(actor_role: str):
    """
    Devuelve la lista de roles que el usuario actual puede asignar a otros.
    """
    actor_role = (actor_role or "").lower()

    if actor_role == "admin":
        # Puede crear cualquiera
        return ["admin", "supervisor", "employee", "user"]

    if actor_role == "supervisor":
        # Puede crear supervisor/employee/user, pero NO admin
        return ["supervisor", "employee", "user"]

    if actor_role == "employee":
        # Puede crear employee o user, pero no subir a nadie a supervisor/admin
        return ["employee", "user"]

    # role == "user" o cualquier otra cosa → no puede crear/editar usuarios
    return []
