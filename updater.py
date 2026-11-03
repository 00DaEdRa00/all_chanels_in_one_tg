"""
Self-updater module for Telegram Feed Aggregator.
Monitors remote Git repository for new commits, pulls updates,
refreshes requirements, and performs hot restarts on server/Docker.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Tuple, Optional

logger = logging.getLogger("Updater")
BASE_DIR = Path(__file__).resolve().parent
RESTART_FILE = BASE_DIR / ".restart_notify.json"


def get_current_commit() -> str:
    """Returns short commit hash of current HEAD."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


async def check_git_updates() -> Tuple[bool, str, int]:
    """
    Checks remote origin/main for new commits.
    Returns (has_update, latest_commit_message, commits_behind_count).
    """
    try:
        # Fetch remote changes
        fetch_proc = await asyncio.create_subprocess_exec(
            "git", "fetch", "origin", "main",
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        await fetch_proc.communicate()

        # Count commits behind
        count_proc = await asyncio.create_subprocess_exec(
            "git", "rev-list", "HEAD...origin/main", "--count",
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, _ = await count_proc.communicate()
        count_str = stdout.decode().strip()
        count = int(count_str) if count_str.isdigit() else 0

        if count > 0:
            msg_proc = await asyncio.create_subprocess_exec(
                "git", "log", "-1", "origin/main", "--pretty=%h: %s",
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            msg_out, _ = await msg_proc.communicate()
            return True, msg_out.decode().strip(), count

        return False, "", 0
    except Exception as e:
        logger.error(f"Error checking git updates: {e}")
        return False, f"Ошибка: {e}", 0


async def apply_git_update() -> Tuple[bool, str]:
    """
    Executes git pull, updates pip dependencies if requirements changed,
    and returns (success, status_message).
    """
    try:
        # 1. Git pull
        pull_proc = await asyncio.create_subprocess_exec(
            "git", "pull", "origin", "main",
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        pull_out, pull_err = await pull_proc.communicate()
        if pull_proc.returncode != 0:
            err_msg = pull_err.decode().strip() or pull_out.decode().strip()
            return False, f"Git pull failed: {err_msg}"

        # 2. Check if requirements.txt changed
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD@{1}", "HEAD", "--name-only",
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        diff_out, _ = await diff_proc.communicate()
        changed_files = diff_out.decode().splitlines()

        if "requirements.txt" in changed_files:
            logger.info("requirements.txt changed! Installing dependencies...")
            pip_proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await pip_proc.communicate()

        new_commit = get_current_commit()
        return True, f"Обновлено до коммита {new_commit}"
    except Exception as e:
        logger.error(f"Failed to apply update: {e}")
        return False, str(e)


def restart_service(notify_chat_id: Optional[int] = None) -> None:
    """
    Prepares restart notification flag and restarts process.
    Supports Docker / systemd (clean exit 0 for daemon reboot)
    or in-place execv replacement.
    """
    if notify_chat_id:
        try:
            with open(RESTART_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "chat_id": notify_chat_id,
                    "previous_commit": get_current_commit()
                }, f)
        except Exception as e:
            logger.warning(f"Could not write restart notification file: {e}")

    logger.info("Restarting process now...")

    # If running inside Docker / systemd supervisor, exit(0) lets Docker restart: unless-stopped trigger
    is_docker = Path("/.dockerenv").exists()
    if is_docker:
        sys.exit(0)
    else:
        # In-place process replacement
        os.execv(sys.executable, [sys.executable] + sys.argv)


async def check_and_notify_post_restart(bot_client) -> None:
    """Checks if a restart occurred and notifies admin."""
    if not RESTART_FILE.exists():
        return

    try:
        with open(RESTART_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        chat_id = data.get("chat_id")
        old_commit = data.get("previous_commit", "prev")
        current_commit = get_current_commit()

        if chat_id:
            await bot_client.send_message(
                chat_id,
                f"✅ **Бот успешно перезапущен после обновления!**\n"
                f"• Предыдущая версия: `{old_commit}`\n"
                f"• Текущая версия: `{current_commit}`"
            )
    except Exception as e:
        logger.warning(f"Error handling post-restart notice: {e}")
    finally:
        try:
            RESTART_FILE.unlink(missing_ok=True)
        except Exception:
            pass
