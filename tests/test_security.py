from erp import security, settings_store


def test_password_hash_roundtrip():
    h = security.hash_password("admin123")
    assert h.startswith("pbkdf2_sha256$")
    assert security.verify_password("admin123", h)
    assert not security.verify_password("errada", h)
    assert security.hash_password("admin123") != h  # salt aleatório


def test_password_policy():
    assert security.password_policy_errors("abc")
    assert security.password_policy_errors("NovaSenha2026") == []


def test_encrypt_decrypt(empty_db):
    token = security.encrypt_value("segredo-ftp")
    assert token.startswith("enc:") and "segredo-ftp" not in token
    assert security.decrypt_value(token) == "segredo-ftp"
    assert security.decrypt_value("texto-puro") == "texto-puro"


def test_env_file_rewritten_encrypted(empty_db):
    path = settings_store.write_env({"FTP_HOST": "192.168.0.50", "FTP_PASSWORD": "S3nh@Forte", "AWS_ACCESS_KEY_ID": "AKIA123"})
    raw = path.read_text()
    assert "192.168.0.50" not in raw and "S3nh@Forte" not in raw and "AKIA123" not in raw
    assert all(v.startswith("enc:") for v in settings_store.read_raw_env(path).values() if v)
    loaded = settings_store.load_connection_settings(path)
    assert loaded["FTP_HOST"] == "192.168.0.50"
    assert loaded["FTP_PASSWORD"] == "S3nh@Forte"
    assert loaded["FTP_PORT"] == "21"  # padrão preservado
    # atualização parcial mantém os demais valores
    settings_store.write_env({"FTP_PORT": "2121"}, path)
    loaded = settings_store.load_connection_settings(path)
    assert loaded["FTP_PORT"] == "2121" and loaded["FTP_PASSWORD"] == "S3nh@Forte"


def test_plaintext_env_values_get_encrypted_on_save(empty_db):
    path = empty_db / ".env"
    path.write_text("FTP_USER=backup\nOUTRA=1\n")
    settings_store.write_env({"FTP_HOST": "ftp.obra.local"}, path)
    raw = settings_store.read_raw_env(path)
    assert raw["FTP_USER"].startswith("enc:")
    assert raw["OUTRA"] == "1"
