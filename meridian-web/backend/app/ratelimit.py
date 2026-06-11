"""Общий Limiter для rate-limit (§5). Импортируется в main.py и роутерах."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
