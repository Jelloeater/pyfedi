# code in this file is from Takahe https://github.com/jointakahe/takahe
#
# Copyright 2022 Andrew Godwin
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
# list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation and/or
# other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

from __future__ import annotations

import base64
import json
from typing import Literal, TypedDict, cast
from urllib.parse import urlparse

import requests
import arrow
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import Request, current_app
from datetime import datetime
from dateutil import parser
from pyld import jsonld

from app.constants import DATETIME_MS_FORMAT


def http_date(epoch_seconds=None):
    if epoch_seconds is None:
        epoch_seconds = arrow.utcnow().timestamp()
    formatted_date = arrow.get(epoch_seconds).format('ddd, DD MMM YYYY HH:mm:ss ZZ', 'en_US')
    return formatted_date


def format_ld_date(value: datetime) -> str:
    # We chop the timestamp to be identical to the timestamps returned by
    # Mastodon's API, because some clients like Toot! (for iOS) are especially
    # picky about timestamp parsing.
    return f"{value.strftime(DATETIME_MS_FORMAT)[:-4]}Z"


def parse_http_date(http_date_str):
    parsed_date = arrow.get(http_date_str, 'ddd, DD MMM YYYY HH:mm:ss Z')
    return parsed_date.datetime


def parse_ld_date(value: str | None) -> datetime | None:
    if value is None:
        return None
    return parser.isoparse(value).replace(microsecond=0)

class VerificationError(BaseException):
    """
    There was an error with verifying the signature
    """

    pass


class VerificationFormatError(VerificationError):
    """
    There was an error with the format of the signature (not if it is valid)
    """

    pass


class RsaKeys:
    @classmethod
    def generate_keypair(cls) -> tuple[str, str]:
        """
        Generates a new RSA keypair
        """
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        private_key_serialized = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        public_key_serialized = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("ascii")
        )
        return private_key_serialized, public_key_serialized


class HttpSignature:
    """
    Allows for calculation and verification of HTTP signatures
    """

    @classmethod
    def calculate_digest(cls, data, algorithm="sha-256") -> str:
        """
        Calculates the digest header value for a given HTTP body
        """
        if algorithm == "sha-256":
            digest = hashes.Hash(hashes.SHA256())
            digest.update(data)
            return "SHA-256=" + base64.b64encode(digest.finalize()).decode("ascii")
        else:
            raise ValueError(f"Unknown digest algorithm {algorithm}")

    @classmethod
    def headers_from_request(cls, request: Request, header_names: list[str]) -> str:
        """
        Creates the to-be-signed header payload from a Flask request
        """
        headers = {}
        for header_name in header_names:
            if header_name == "(request-target)":
                value = f"{request.method.lower()} {request.path}"
            elif header_name == "content-type":
                value = request.headers.get("Content-Type", "")
            elif header_name == "content-length":
                value = request.headers.get("Content-Length", "")
            else:
                value = request.headers.get(header_name.replace("-", "_").upper(), "")
            headers[header_name] = value
        return "\n".join(f"{name.lower()}: {value}" for name, value in headers.items())

    @classmethod
    def parse_signature(cls, signature: str) -> "HttpSignatureDetails":
        bits = {}
        for item in signature.split(","):
            name, value = item.split("=", 1)
            value = value.strip('"')
            bits[name.lower()] = value
        try:
            signature_details: HttpSignatureDetails = {
                "headers": bits["headers"].split(),
                "signature": base64.b64decode(bits["signature"]),
                "algorithm": bits["algorithm"],
                "keyid": bits["keyid"],
            }
        except KeyError as e:
            key_names = " ".join(bits.keys())
            raise VerificationError(
                f"Missing item from details (have: {key_names}, error: {e})"
            )
        return signature_details

    @classmethod
    def compile_signature(cls, details: "HttpSignatureDetails") -> str:
        value = f'keyId="{details["keyid"]}",headers="'
        value += " ".join(h.lower() for h in details["headers"])
        value += '",signature="'
        value += base64.b64encode(details["signature"]).decode("ascii")
        value += f'",algorithm="{details["algorithm"]}"'
        return value

    @classmethod
    def verify_signature(
        cls,
        signature: bytes,
        cleartext: str,
        public_key: str,
    ):
        public_key_instance: rsa.RSAPublicKey = cast(
            rsa.RSAPublicKey,
            serialization.load_pem_public_key(public_key.encode("ascii")),
        )
        try:
            public_key_instance.verify(
                signature,
                cleartext.encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            raise VerificationError("Signature mismatch")

    @classmethod
    def verify_request(cls, request: Request, public_key, skip_date=False):
        """
        Verifies that the request has a valid signature for its body
        """
        # Verify body digest
        if "digest" in request.headers:
            expected_digest = HttpSignature.calculate_digest(request.data)
            if request.headers["digest"] != expected_digest:
                raise VerificationFormatError("Digest is incorrect")

        # Verify date header
        if "date" in request.headers and not skip_date:
            header_date = parse_http_date(request.headers["date"])
            if abs((arrow.utcnow() - header_date).total_seconds()) > 3600:
                raise VerificationFormatError("Date is too far away")

        # Get the signature details
        if "signature" not in request.headers:
            raise VerificationFormatError("No signature header present")
        signature_details = cls.parse_signature(request.headers["signature"])

        # Reject unknown algorithms
        # hs2019 is used by some libraries to obfuscate the real algorithm per the spec
        # https://datatracker.ietf.org/doc/html/draft-cavage-http-signatures-12
        if (
            signature_details["algorithm"] != "rsa-sha256"
            and signature_details["algorithm"] != "hs2019"
        ):
            raise VerificationFormatError("Unknown signature algorithm")
        # Create the signature payload
        headers_string = cls.headers_from_request(request, signature_details["headers"])
        cls.verify_signature(
            signature_details["signature"],
            headers_string,
            public_key,
        )
        return True

    @classmethod
    def signed_request(
        cls,
        uri: str,
        body: dict | None,
        private_key: str,
        key_id: str,
        content_type: str = "application/json",
        method: Literal["get", "post"] = "post",
        timeout: int = 5,
    ):
        """
        Performs a request to the given path, with a document, signed
        as an identity.
        """
        if "://" not in uri:
            raise ValueError("URI does not contain a scheme")
        # Create the core header field set
        uri_parts = urlparse(uri)
        date_string = http_date()
        headers = {
            "(request-target)": f"{method} {uri_parts.path}",
            "Host": uri_parts.hostname,
            "Date": date_string,
        }
        # If we have a body, add a digest and content type
        if body is not None:
            if '@context' not in body:                          # add a default json-ld context if necessary
                body['@context'] = [
                    "https://www.w3.org/ns/activitystreams",
                    "https://w3id.org/security/v1",
                    {
                      "piefed": "https://piefed.social/ns#",
                      "lemmy": "https://join-lemmy.org/ns#",
                      "litepub": "http://litepub.social/ns#",
                      "pt": "https://joinpeertube.org/ns#",
                      "sc": "http://schema.org/",
                      "nsfl": "piefed:nsfl",
                      "ChatMessage": "litepub:ChatMessage",
                      "commentsEnabled": "pt:commentsEnabled",
                      "sensitive": "as:sensitive",
                      "matrixUserId": "lemmy:matrixUserId",
                      "postingRestrictedToMods": "lemmy:postingRestrictedToMods",
                      "removeData": "lemmy:removeData",
                      "stickied": "lemmy:stickied",
                      "moderators": {
                        "@type": "@id",
                        "@id": "lemmy:moderators"
                      },
                      "expires": "as:endTime",
                      "distinguished": "lemmy:distinguished",
                      "language": "sc:inLanguage",
                      "identifier": "sc:identifier"
                    }
                ]
            body_bytes = json.dumps(body).encode("utf8")
            headers["Digest"] = cls.calculate_digest(body_bytes)
            headers["Content-Type"] = content_type
        else:
            body_bytes = b""
        # GET requests get implicit accept headers added
        if method == "get":
            headers["Accept"] = "application/ld+json"
        # Sign the headers
        signed_string = "\n".join(
            f"{name.lower()}: {value}" for name, value in headers.items()
        )
        private_key_instance: rsa.RSAPrivateKey = cast(
            rsa.RSAPrivateKey,
            serialization.load_pem_private_key(
                private_key.encode("ascii"),
                password=None,
            ),
        )
        signature = private_key_instance.sign(
            signed_string.encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        headers["Signature"] = cls.compile_signature(
            {
                "keyid": key_id,
                "headers": list(headers.keys()),
                "signature": signature,
                "algorithm": "rsa-sha256",
            }
        )

        headers["User-Agent"] = 'PieFed/1.0'

        # Send the request with all those headers except the pseudo one
        del headers["(request-target)"]
        try:
            response = requests.request(
                method,
                uri,
                headers=headers,
                data=body_bytes,
                timeout=timeout,
                allow_redirects=method == "GET",
            )
        except requests.exceptions.SSLError as invalid_cert:
            # Not our problem if the other end doesn't have proper SSL
            current_app.logger.info(f"{uri} {invalid_cert}")
            raise requests.exceptions.SSLError from invalid_cert
        except ValueError as ex:
            # Convert to a more generic error we handle
            raise requests.exceptions.RequestException(f"InvalidCodepoint: {str(ex)}") from None

        if (
                method == "POST"
                and 400 <= response.status_code < 500
                and response.status_code != 404
        ):
            raise ValueError(
                f"POST error to {uri}: {response.status_code} {response.content!r}"
            )

        return response


class HttpSignatureDetails(TypedDict):
    algorithm: str
    headers: list[str]
    signature: bytes
    keyid: str


class LDSignature:
    """
    Creates and verifies signatures of JSON-LD documents
    """

    @classmethod
    def verify_signature(cls, document: dict, public_key: str) -> None:
        """
        Verifies a document
        """
        try:
            # Strip out the signature from the incoming document
            signature = document.pop("signature")
            # Create the options document
            options = {
                "@context": "https://w3id.org/identity/v1",
                "creator": signature["creator"],
                "created": signature["created"],
            }
        except KeyError:
            raise VerificationFormatError("Invalid signature section")
        if signature["type"].lower() != "rsasignature2017":
            raise VerificationFormatError("Unknown signature type")
        # Get the normalised hash of each document
        final_hash = cls.normalized_hash(options) + cls.normalized_hash(document)
        # Verify the signature
        public_key_instance: rsa.RSAPublicKey = cast(
            rsa.RSAPublicKey,
            serialization.load_pem_public_key(public_key.encode("ascii")),
        )
        try:
            public_key_instance.verify(
                base64.b64decode(signature["signatureValue"]),
                final_hash,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            raise VerificationError("Signature mismatch")

    @classmethod
    def create_signature(
        cls, document: dict, private_key: str, key_id: str
    ) -> dict[str, str]:
        """
        Creates the signature for a document
        """
        # Create the options document
        options: dict[str, str] = {
            "@context": "https://w3id.org/identity/v1",
            "creator": key_id,
            "created": format_ld_date(datetime.utcnow()),
        }
        # Get the normalised hash of each document
        final_hash = cls.normalized_hash(options) + cls.normalized_hash(document)
        # Create the signature
        private_key_instance: rsa.RSAPrivateKey = cast(
            rsa.RSAPrivateKey,
            serialization.load_pem_private_key(
                private_key.encode("ascii"),
                password=None,
            ),
        )
        signature = base64.b64encode(
            private_key_instance.sign(
                final_hash,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        )
        # Add it to the options document along with other bits
        options["signatureValue"] = signature.decode("ascii")
        options["type"] = "RsaSignature2017"
        return options

    @classmethod
    def normalized_hash(cls, document) -> bytes:
        """
        Takes a JSON-LD document and create a hash of its URDNA2015 form,
        in the same way that Mastodon does internally.

        Reference: https://socialhub.activitypub.rocks/t/making-sense-of-rsasignature2017/347
        """
        norm_form = jsonld.normalize(
            document,
            {"algorithm": "URDNA2015", "format": "application/n-quads"},
        )
        digest = hashes.Hash(hashes.SHA256())
        digest.update(norm_form.encode("utf8"))
        return digest.finalize().hex().encode("ascii")
