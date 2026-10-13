"""
RPC credentials of the bundled Monacoin Core node.

The package ships node/monacoin.conf.template with a well-known placeholder password. Every
installation gets its own random password in node/monacoin.conf on the first launch, so that
no two installations (and no published default) share the credentials that control the node
and its wallet.
"""
import os
import re
import secrets
import shutil
from typing import Callable, Optional, Tuple

CONF_NAME = "monacoin.conf"
TEMPLATE_NAME = "monacoin.conf.template"
DEFAULT_RPC_PASSWORD = "rpcpassword"  # placeholder shipped in the template (and in v2.2.2 and older)

_PASSWORD_LINE = re.compile(r"^([ \t]*rpcpassword[ \t]*=[ \t]*)(.*?)(?=[ \t\r]*$)", re.MULTILINE)


def read_rpc_password(conf_path: str) -> Optional[str]:
    try:
        with open(conf_path, "r", encoding="utf-8") as f:
            m = _PASSWORD_LINE.search(f.read())
    except OSError:
        return None
    return m.group(2) if m else None


def ensure_rpc_password(node_dir: str,
                        node_uses_default: Optional[Callable[[], bool]] = None) -> Tuple[Optional[str], bool]:
    """
    Makes sure node/monacoin.conf exists and does not use the placeholder password.
    Returns (password in the conf or None when there is no bundled node, True when it was just replaced).

    `node_uses_default` tells whether a node is running right now with the placeholder password:
    the conf is then left alone (a running node keeps the password it was started with, so the
    miner would lose its connection) and replaced on a later launch.
    """
    conf_path = os.path.join(node_dir, CONF_NAME)
    if not os.path.exists(conf_path):
        template = os.path.join(node_dir, TEMPLATE_NAME)
        if not os.path.exists(template):
            return None, False
        shutil.copyfile(template, conf_path)

    password = read_rpc_password(conf_path)
    if password != DEFAULT_RPC_PASSWORD:
        return password, False
    if node_uses_default is not None and node_uses_default():
        return password, False

    new_password = secrets.token_urlsafe(24)
    with open(conf_path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    text = _PASSWORD_LINE.sub(lambda m: m.group(1) + new_password, text, count=1)
    tmp_path = conf_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp_path, conf_path)
    return new_password, True
