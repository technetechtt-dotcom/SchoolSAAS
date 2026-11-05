"""Encrypt authenticator secrets at rest with a distinct high-entropy key.

MFA_ENCRYPTION_KEY is mandatory when configuring MFA. Existing plaintext MFA secrets
must be reset/re-enrolled before enforcement. This module never logs secrets.
"""
import os
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

def cipher():
    key=os.getenv("MFA_ENCRYPTION_KEY","")
    if len(key)<32:
        raise HTTPException(503,"MFA encryption key is not configured")
    try:
        return Fernet(key.encode())
    except (ValueError,TypeError):
        raise HTTPException(503,"MFA encryption key is invalid; use a Fernet key")

def encrypt_secret(secret:str)->str:
    return "enc:" + cipher().encrypt(secret.encode()).decode()

def decrypt_secret(stored:str)->str:
    if not stored or not stored.startswith("enc:"):
        raise HTTPException(503,"Legacy MFA enrollment requires secure reset and re-enrollment")
    try:
        return cipher().decrypt(stored[4:].encode()).decode()
    except InvalidToken:
        raise HTTPException(503,"MFA encryption key mismatch")
