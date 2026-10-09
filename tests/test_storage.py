import ftplib
from unittest.mock import MagicMock, patch

from erp import db
from erp.storage import DualStorage, FTPBackend, S3Backend, build_key, store_media

SETTINGS = {
    "AWS_ACCESS_KEY_ID": "AKIA_TEST", "AWS_SECRET_ACCESS_KEY": "secret", "AWS_REGION": "sa-east-1",
    "S3_BUCKET": "obra-prod", "S3_PREFIX": "obra",
    "FTP_HOST": "10.0.0.5", "FTP_PORT": "21", "FTP_USER": "backup", "FTP_PASSWORD": "pw", "FTP_BASE_DIR": "/backup_obra",
}


def test_key_structure():
    key = build_key("Fotos Obra", "foto 01.jpg")
    parts = key.split("/")
    assert parts[0] == "fotos_obra" and len(parts) == 4 and parts[-1].endswith("foto_01.jpg")


def test_local_only_when_not_configured(tmp_path):
    st = DualStorage(settings={}, local_root=tmp_path)
    r = st.save(b"abc", "a.txt", "teste")
    assert r.local == "ok" and r.s3 == "não configurado" and r.ftp == "não configurado"
    assert st.load(r.key) == b"abc"


def test_simultaneous_upload_to_s3_and_ftp(tmp_path):
    s3_client = MagicMock()
    ftp = MagicMock()
    ftp.cwd.side_effect = [None, ftplib.error_perm("550 pasta inexistente")] + [None] * 20
    with patch("boto3.client", return_value=s3_client) as boto_client, patch("ftplib.FTP", return_value=ftp):
        st = DualStorage(settings=SETTINGS, local_root=tmp_path)
        r = st.save(b"conteudo", "nf.png", "notas-fiscais")
    assert r.s3 == "ok" and r.ftp == "ok", r.errors
    boto_client.assert_called_once()
    kwargs = s3_client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "obra-prod" and kwargs["Key"] == f"obra/{r.key}" and kwargs["Body"] == b"conteudo"
    ftp.connect.assert_called_with("10.0.0.5", 21, timeout=15)
    ftp.login.assert_called_with("backup", "pw")
    assert ftp.storbinary.call_args.args[0].startswith("STOR ")
    assert ftp.mkd.called  # cria a estrutura de pastas do backup
    assert (tmp_path / r.key).read_bytes() == b"conteudo"


def test_one_backend_failing_does_not_block_the_other(tmp_path):
    s3_client = MagicMock()
    s3_client.put_object.side_effect = RuntimeError("AccessDenied")
    with patch("boto3.client", return_value=s3_client), patch("ftplib.FTP", return_value=MagicMock()):
        r = DualStorage(settings=SETTINGS, local_root=tmp_path).save(b"x", "a.jpg", "fotos")
    assert r.s3 == "erro" and r.ftp == "ok"
    assert any("AccessDenied" in e for e in r.errors)


def test_ftp_connection_test_button_logic():
    ftp = MagicMock()
    ftp.getwelcome.return_value = "220 Backup FTP"
    ftp.pwd.return_value = "/"
    with patch("ftplib.FTP", return_value=ftp):
        ok, msg = FTPBackend(SETTINGS).test()
    assert ok and "10.0.0.5" in msg
    with patch("ftplib.FTP", side_effect=OSError("timed out")):
        ok, msg = FTPBackend(SETTINGS).test()
    assert not ok and "timed out" in msg
    assert FTPBackend({}).test()[0] is False


def test_s3_connection_test():
    client = MagicMock()
    with patch("boto3.client", return_value=client):
        ok, _ = S3Backend(SETTINGS).test()
    assert ok
    client.head_bucket.assert_called_with(Bucket="obra-prod")


def test_store_media_records_status(empty_db):
    r = store_media(b"img", "foto.jpg", "fotos-obra")
    row = db.query_one("SELECT * FROM media WHERE key = ?", (r.key,))
    assert row["local_status"] == "ok" and row["size_bytes"] == 3


def test_load_falls_back_to_remote(tmp_path):
    client = MagicMock()
    client.get_object.return_value = {"Body": MagicMock(read=lambda: b"remoto")}
    with patch("boto3.client", return_value=client):
        st = DualStorage(settings=SETTINGS, local_root=tmp_path)
        assert st.load("fotos/2026/10/x.jpg") == b"remoto"
    assert (tmp_path / "fotos/2026/10/x.jpg").read_bytes() == b"remoto"
