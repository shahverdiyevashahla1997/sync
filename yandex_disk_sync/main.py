import os
import time
from datetime import datetime

from dotenv import dotenv_values
from loguru import logger

from yandex_disk import YandexDisk


def read_config(config_path=".env"):
    """Read and validate application settings."""
    config = dotenv_values(config_path)
    required = ("LOCAL_FOLDER", "REMOTE_FOLDER", "YANDEX_TOKEN", "SYNC_INTERVAL", "LOG_FILE")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(
            "Не заполнены параметры в .env: "
            + ", ".join(missing)
            + ". Заполните их и запустите программу повторно."
        )

    try:
        interval = int(config["SYNC_INTERVAL"])
    except (TypeError, ValueError) as exc:
        raise ValueError("SYNC_INTERVAL должен быть целым числом секунд.") from exc

    if interval < 1:
        raise ValueError("SYNC_INTERVAL должен быть не меньше 1 секунды.")

    local_folder = os.path.abspath(os.path.expanduser(config["LOCAL_FOLDER"]))
    if not os.path.isdir(local_folder):
        raise ValueError(
            f"Локальная папка не существует: {local_folder}. "
            "Создайте папку или исправьте LOCAL_FOLDER в .env."
        )

    return {
        "local_folder": local_folder,
        "remote_folder": config["REMOTE_FOLDER"].strip("/"),
        "token": config["YANDEX_TOKEN"].strip(),
        "interval": interval,
        "log_file": os.path.abspath(os.path.expanduser(config["LOG_FILE"])),
    }


def setup_logger(log_file):
    """Configure console and file logging."""
    logger.remove()
    logger.add(
        log_file,
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        rotation="5 MB",
        retention=3,
        encoding="utf-8",
    )
    logger.add(
        lambda message: print(message, end=""),
        level="INFO",
        format="{time:HH:mm:ss} | {level} | {message}",
    )




def sync_once(cloud, local_folder):
    """Synchronize top-level local files with cloud storage."""
    try:
        cloud_files = cloud.get_info()
    except Exception as exc:
        logger.error("Не удалось получить список файлов в облаке: {}", exc)
        return

    try:
        local_names = os.listdir(local_folder)
    except OSError as exc:
        logger.error("Не удалось прочитать локальную папку {}: {}", local_folder, exc)
        return

    local_files = {
        name
        for name in local_names
        if os.path.isfile(os.path.join(local_folder, name))
    }

    for filename in set(cloud_files) - local_files:
        try:
            cloud.delete(filename)
            logger.info("Удалён из облака: {}", filename)
        except Exception as exc:
            logger.error("Не удалось удалить {} из облака: {}", filename, exc)

    for filename in local_files:
        local_path = os.path.join(local_folder, filename)

        try:
            local_size = os.path.getsize(local_path)
            local_md5 = cloud._file_md5(local_path)
            remote = cloud_files.get(filename)

            if remote is None:
                cloud.load(local_path)
                logger.info("Загружен новый файл: {}", filename)
                continue

            remote_md5 = remote.get("md5")
            remote_size = remote.get("size")

            changed = (
                remote_md5 is not None
                and local_md5.lower() != remote_md5.lower()
            )

            if remote_size is not None and int(remote_size) != local_size:
                changed = True

            if changed:
                cloud.reload(local_path)
                logger.info("Обновлён файл: {}", filename)

        except (OSError, ValueError, TypeError) as exc:
            logger.error("Ошибка чтения локального файла {}: {}", filename, exc)
        except Exception as exc:
            logger.error("Ошибка синхронизации файла {}: {}", filename, exc)




def main():
    """Load configuration and run the periodic synchronization loop."""
    try:
        config = read_config()
    except (ValueError, OSError) as exc:
        print(f"Ошибка настроек: {exc}")
        return

    setup_logger(config["log_file"])
    logger.info("Запуск программы синхронизации")
    logger.info("Локальная папка: {}", config["local_folder"])
    logger.info("Папка на Яндекс Диске: {}", config["remote_folder"])

    try:
        cloud = YandexDisk(config["token"], config["remote_folder"])
        cloud.validate_access()
    except Exception as exc:
        logger.error("Не удалось подключиться к Яндекс Диску: {}", exc)
        print(
            "Не удалось подключиться к Яндекс Диску. Проверьте OAuth-токен "
            "и доступ к интернету. Подробности записаны в лог."
        )
        return

    while True:
        logger.info("Начало цикла синхронизации: {}", datetime.now().isoformat(timespec="seconds"))
        sync_once(cloud, config["local_folder"])
        time.sleep(config["interval"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Работа программы остановлена пользователем.")
        print("\nСинхронизация остановлена.")
