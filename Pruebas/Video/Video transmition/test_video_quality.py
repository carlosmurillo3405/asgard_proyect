"""Pruebas de los perfiles salientes y la resolución de cuadros recibidos."""

import unittest

import cv2
import numpy as np

from Midgard_video_transmition import (
    TRANSMISSION_PROFILES,
    _decode_received_frame,
    _prepare_frame,
)


class TransmissionProfileTests(unittest.TestCase):
    """Comprueba que cada perfil limita el envío y conserva la proporción."""

    def test_profiles_reduce_a_full_hd_frame_to_their_maximum_size(self) -> None:
        """Cada perfil reduce el cuadro 16:9 a su límite máximo configurado."""
        source = np.zeros((1080, 1920, 3), dtype=np.uint8)

        for profile in TRANSMISSION_PROFILES.values():
            with self.subTest(profile=profile):
                result = _prepare_frame(source, profile)

                self.assertLessEqual(result.shape[1], profile.max_width)
                self.assertLessEqual(result.shape[0], profile.max_height)
                self.assertAlmostEqual(
                    result.shape[1] / result.shape[0], 16 / 9, places=2
                )

    def test_small_source_is_not_upscaled(self) -> None:
        """El perfil alto no inventa resolución si la cámara produce menos."""
        source = np.zeros((240, 320, 3), dtype=np.uint8)
        result = _prepare_frame(source, TRANSMISSION_PROFILES["Buena"])

        self.assertIs(result, source)


class ReceiveQualityTests(unittest.TestCase):
    """Verifica que la decodificación conserva la resolución recibida."""

    def test_received_frame_is_not_scaled_down(self) -> None:
        """Un cuadro JPEG Full HD permanece Full HD después de decodificarse."""
        source = np.zeros((1080, 1920, 3), dtype=np.uint8)
        encoded, jpeg = cv2.imencode(".jpg", source)
        self.assertTrue(encoded)

        received = _decode_received_frame(jpeg.tobytes())

        self.assertEqual(received.shape, source.shape)


if __name__ == "__main__":
    # Permite ejecutar estas pruebas directamente o mediante unittest discovery.
    unittest.main()
