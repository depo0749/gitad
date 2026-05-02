#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yerel bir klasörü GitHub deposuna birebir yükler (git ile tüm dosya/klasör yapısı korunur).
Mevcut depo kullanılabilir veya GitHub API ile yeni depo oluşturulabilir.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

try:
    from github import Auth, Github, GithubException
except ImportError:
    print("Önce bagimliliklari kurun: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


def run_git(cwd: Path, args: list[str], env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, **(env or {})},
    )


def require_git() -> None:
    if shutil.which("git") is None:
        print(
            "HATA: 'git' bulunamadi. Git for Windows kurun ve PATH'e ekleyin:\n"
            "https://git-scm.com/download/win",
            file=sys.stderr,
        )
        sys.exit(1)


def get_remote_url_with_token(owner: str, repo: str, token: str) -> str:
    """HTTPS URL; token URL icinde (gecici push icin)."""
    safe = quote(token, safe="")
    return f"https://x-access-token:{safe}@github.com/{owner}/{repo}.git"


def parse_repo_arg(repo: str) -> tuple[str, str]:
    """owner/repo veya https://github.com/owner/repo -> (owner, repo_name)."""
    s = repo.strip().rstrip("/")
    if "github.com" in s:
        part = s.split("github.com/", 1)[-1]
        part = part.removesuffix(".git")
        segs = [p for p in part.split("/") if p]
        if len(segs) >= 2:
            return segs[0], segs[1]
    if "/" in s:
        a, b = s.split("/", 1)
        return a.strip(), b.strip().removesuffix(".git")
    raise ValueError(f"Depo formati anlasilamadi: {repo!r}. Ornek: kullanici/proje-adı")


def ensure_repo_exists(
    token: str,
    owner: str,
    repo_name: str,
    *,
    private: bool,
    description: str | None,
) -> None:
    auth = Auth.Token(token)
    g = Github(auth=auth)
    try:
        g.get_repo(f"{owner}/{repo_name}")
        return
    except GithubException as e:
        if e.status != 404:
            raise

    print(f"Depo yok, olusturuluyor: {owner}/{repo_name} ...")
    user = g.get_user()
    desc = description or ""
    try:
        if user.login.lower() == owner.lower():
            user.create_repo(repo_name, private=private, description=desc, auto_init=False)
        else:
            org = g.get_organization(owner)
            org.create_repo(repo_name, private=private, description=desc, auto_init=False)
    except GithubException as e:
        print(f"HATA: Depo olusturulamadi: {e}", file=sys.stderr)
        sys.exit(1)


def init_git_if_needed(root: Path, branch: str) -> None:
    git_dir = root / ".git"
    if git_dir.is_dir():
        return
    r = run_git(root, ["init", "-b", branch])
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        sys.exit(1)


def set_origin(root: Path, url: str) -> None:
    r = run_git(root, ["remote", "get-url", "origin"])
    if r.returncode == 0:
        r = run_git(root, ["remote", "set-url", "origin", url])
    else:
        r = run_git(root, ["remote", "add", "origin", url])
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        sys.exit(1)


def git_add_commit(root: Path, message: str, no_verify: bool) -> None:
    r = run_git(root, ["add", "-A"])
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        sys.exit(1)
    st = run_git(root, ["status", "--porcelain"])
    if not (st.stdout or "").strip():
        print("Degisiklik yok; mevcut commit'ler itilecek.")
        return
    args = ["commit", "-m", message]
    if no_verify:
        args.insert(1, "--no-verify")
    r = run_git(root, args)
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        sys.exit(1)


def git_push(root: Path, branch: str, force: bool) -> None:
    args = ["push", "-u", "origin", branch]
    if force:
        args.insert(1, "--force")
    r = run_git(root, args)
    if r.returncode != 0:
        print(r.stderr or r.stdout, file=sys.stderr)
        sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Yerel projeyi GitHub'a yukler (klasorler ve tum dosyalar git ile)."
    )
    p.add_argument(
        "kaynak_pos",
        nargs="?",
        type=Path,
        default=None,
        metavar="KLASOR",
        help="Yuklenecek klasor (opsiyonel; yoksa simdiki dizin veya --kaynak)",
    )
    p.add_argument(
        "--kaynak",
        type=Path,
        default=Path.cwd(),
        help="Yuklenecek klasor (--kaynak veya ilk konumsal KLASOR; ikisi birden varsa KLASOR kullanilir)",
    )
    p.add_argument(
        "--depo",
        required=True,
        help="Hedef: sahip/repo veya https://github.com/sahip/repo",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
        help="GitHub PAT (veya ortam degiskeni GITHUB_TOKEN / GH_TOKEN)",
    )
    p.add_argument(
        "--olustur",
        action="store_true",
        help="Depo yoksa GitHub'da bos depo olustur",
    )
    p.add_argument("--ozel", action="store_true", help="Yeni depo ozel (private) olsun")
    p.add_argument("--aciklama", default="", help="Yeni depo aciklamasi")
    p.add_argument("--dal", default="main", help="Git dal adi (varsayilan: main)")
    p.add_argument(
        "--mesaj",
        default="Proje yuklemesi",
        help="Commit mesaji",
    )
    p.add_argument(
        "--zorla-it",
        action="store_true",
        help="Uzak dali ezerek push (dikkatli kullanin)",
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="git commit --no-verify",
    )
    args = p.parse_args()
    kaynak = args.kaynak_pos if args.kaynak_pos is not None else args.kaynak

    if not args.token:
        print(
            "HATA: Token gerekli. --token veya GITHUB_TOKEN / GH_TOKEN ortam degiskeni.",
            file=sys.stderr,
        )
        sys.exit(1)

    require_git()
    root = kaynak.resolve()
    if not root.is_dir():
        print(f"HATA: Klasor yok: {root}", file=sys.stderr)
        sys.exit(1)

    try:
        owner, repo_name = parse_repo_arg(args.depo)
    except ValueError as e:
        print(f"HATA: {e}", file=sys.stderr)
        sys.exit(1)

    if args.olustur:
        ensure_repo_exists(
            args.token,
            owner,
            repo_name,
            private=args.ozel,
            description=args.aciklama or None,
        )

    remote_url = get_remote_url_with_token(owner, repo_name, args.token)
    init_git_if_needed(root, args.dal)
    set_origin(root, remote_url)

    git_add_commit(root, args.mesaj, args.no_verify)
    print(f"Gonderiliyor: {owner}/{repo_name} ({args.dal}) ...")
    git_push(root, args.dal, args.zorla_it)
    print("Tamam. Depo guncellendi:", f"https://github.com/{owner}/{repo_name}")


if __name__ == "__main__":
    main()
