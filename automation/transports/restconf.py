"""
RESTCONF transport for IOS XE devices.
Provides GET and PATCH methods with self-signed certificate handling.
"""
import requests
from requests.auth import HTTPBasicAuth
from urllib3.exceptions import InsecureRequestWarning
import logging

# Suppress insecure HTTPS warnings for self-signed certs
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

logger = logging.getLogger(__name__)

def restconf_get(host, port=443, username=None, password=None, path="/restconf/data"):
    """
    Send a RESTCONF GET request.
    :param host: IP or hostname
    :param port: HTTPS port (default 443)
    :param username, password: HTTP Basic Auth
    :param path: RESTCONF path (default /restconf/data)
    :return: response JSON (dict) or None on failure
    """
    url = f"https://{host}:{port}{path}"
    headers = {"Accept": "application/yang-data+json"}
    auth = HTTPBasicAuth(username, password) if username and password else None

    try:
        response = requests.get(url, headers=headers, auth=auth, verify=False)
        if response.status_code == 200:
            logger.info(f"RESTCONF GET to {host} succeeded")
            return response.json()
        else:
            logger.error(f"RESTCONF GET to {host} failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"RESTCONF GET connection error to {host}: {e}")
        return None

def restconf_patch(host, port=443, username=None, password=None, data=None, path="/restconf/data"):
    """
    Send a RESTCONF PATCH request.
    :param host: IP or hostname
    :param port: HTTPS port (default 443)
    :param username, password: HTTP Basic Auth
    :param data: Python dict representing YANG data to patch
    :param path: RESTCONF path (default /restconf/data)
    :return: True if successful, False otherwise
    """
    url = f"https://{host}:{port}{path}"
    headers = {
        "Content-Type": "application/yang-data+json",
        "Accept": "application/yang-data+json"
    }
    auth = HTTPBasicAuth(username, password) if username and password else None

    try:
        response = requests.patch(url, json=data, headers=headers, auth=auth, verify=False)
        if response.status_code in [200, 201, 204]:
            logger.info(f"RESTCONF PATCH to {host} succeeded: {response.status_code}")
            return True
        else:
            logger.error(f"RESTCONF PATCH to {host} failed: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"RESTCONF PATCH connection error to {host}: {e}")
        return False