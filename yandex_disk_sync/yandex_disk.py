
import hashlib
import os

import requests


class YandexDiskError(RuntimeError):
    """Ошибка взаимодействия с API Яндекс Диска."""


class YandexDisk:
    """Класс для работы с резервной папкой на Яндекс Диске."""

    API_BASE = "https://cloud-api.yandex.net/v1/disk"

    def __init__(self, token, remote_folder):
        if not token or not token.strip():
            raise ValueError("Не указан OAuth-токен Яндекс Диска.")

        if not remote_folder or not remote_folder.strip("/"):
            raise ValueError("Не указано имя папки на Яндекс Диске.")

        self.remote_folder = remote_folder.strip("/")
        self.timeout = 30
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"OAuth {token.strip()}"
        })

        self._ensure_remote_folder()

    def _request(self, method, url, expected_statuses=(), **kwargs):
        """Выполнить запрос и обработать ошибки API и сети."""
        try:
            response = self.session.request(
                method,
                url,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise YandexDiskError(
                f"Сетевая ошибка при обращении к Яндекс Диску: {exc}"
            ) from exc

        if response.status_code >= 400:
            if response.status_code in expected_statuses:
                return response

            detail = response.text[:500]
            hint = ""

            if response.status_code == 401:
                hint = " Проверьте OAuth-токен."
            elif response.status_code == 403:
                hint = " Проверьте разрешения OAuth-токена."
            elif response.status_code == 404:
                hint = " Проверьте путь к ресурсу."

            raise YandexDiskError(
                f"Ошибка API Яндекс Диска "
                f"(HTTP {response.status_code}): {detail}.{hint}"
            )

        return response

    def _resource_path(self, filename=None):
        """Сформировать путь к папке или файлу на диске."""
        path = f"disk:/{self.remote_folder}"

        if filename is not None:
            path = f"{path}/{filename}"

        return path

    def _ensure_remote_folder(self):
        """Создать резервную папку, если она ещё не существует."""
        url = f"{self.API_BASE}/resources"
        params = {"path": self._resource_path()}

        response = self._request(
            "GET",
            url,
            expected_statuses=(404,),
            params=params,
        )

        if response.status_code == 200:
            return

        self._request(
            "PUT",
            url,
            expected_statuses=(409,),
            params=params,
        )

    def validate_access(self):
        """Проверить доступ к API Яндекс Диска."""
        self._request("GET", f"{self.API_BASE}/")

    def get_info(self):
        """Получить метаданные файлов в резервной папке."""
        url = f"{self.API_BASE}/resources"
        params = {
            "path": self._resource_path(),
            "limit": 1000,
            "fields": (
                "_embedded.items.name,"
                "_embedded.items.type,"
                "_embedded.items.modified,"
                "_embedded.items.size,"
                "_embedded.items.md5"
            ),
        }

        response = self._request("GET", url, params=params)

        try:
            payload = response.json()
        except ValueError as exc:
            raise YandexDiskError(
                "Яндекс Диск вернул некорректный JSON."
            ) from exc

        result = {}

        for item in payload.get("_embedded", {}).get("items", []):
            if item.get("type") != "file" or not item.get("name"):
                continue

            result[item["name"]] = {
                "modified": item.get("modified"),
                "size": item.get("size"),
                "md5": item.get("md5"),
            }

        return result

    @staticmethod
    def _file_md5(path):
        """Вычислить MD5-хеш локального файла."""
        digest = hashlib.md5()

        with open(path, "rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                digest.update(chunk)

        return digest.hexdigest()

    def _upload(self, path, overwrite):
        """Загрузить файл на Яндекс Диск."""
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Файл не найден: {path}")

        filename = os.path.basename(path)
        params = {
            "path": self._resource_path(filename),
            "overwrite": str(overwrite).lower(),
        }

        response = self._request(
            "GET",
            f"{self.API_BASE}/resources/upload",
            params=params,
        )

        try:
            href = response.json()["href"]
        except (ValueError, KeyError) as exc:
            raise YandexDiskError(
                "В ответе API отсутствует URL загрузки."
            ) from exc

        try:
            with open(path, "rb") as file_obj:
                upload_response = requests.put(
                    href,
                    data=file_obj,
                    timeout=self.timeout,
                )
        except (OSError, requests.RequestException) as exc:
            raise YandexDiskError(
                f"Не удалось прочитать или загрузить "
                f"{filename}: {exc}"
            ) from exc

        if upload_response.status_code not in (200, 201, 202):
            raise YandexDiskError(
                f"Ошибка загрузки {filename}: "
                f"HTTP {upload_response.status_code}, "
                f"{upload_response.text[:300]}"
            )

    def load(self, path):
        """Загрузить новый файл."""
        self._upload(path, overwrite=False)

    def reload(self, path):
        """Перезаписать файл его локальной версией."""
        self._upload(path, overwrite=True)

    def delete(self, filename):
        """Удалить файл из резервной папки."""
        response = self._request(
            "DELETE",
            f"{self.API_BASE}/resources",
            expected_statuses=(404,),
            params={
                "path": self._resource_path(filename),
                "permanently": "false",
            },
        )

        if response.status_code == 404:
            return

