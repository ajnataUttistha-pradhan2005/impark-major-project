"""Conservative input quality checks; these are not a botanical classifier."""

import io

import numpy as np
from PIL import Image, ImageOps

from backend.contracts.agents import ImageQualityResult


def assess_quality(content: bytes) -> ImageQualityResult:
    with Image.open(io.BytesIO(content)) as original:
        image = ImageOps.exif_transpose(original).convert("L")
        issues = []
        if min(image.size) < 64:
            issues.append("Image resolution is too low; upload a clear close-up of a leaf")
        image.thumbnail((256, 256))
        gray = np.asarray(image, dtype=np.float32)
        if float(gray.std()) < 5:
            issues.append("Image has too little visual detail")
        if float(gray.mean()) < 12 or float(gray.mean()) > 245:
            issues.append("Image is severely underexposed or overexposed")
        if min(gray.shape) >= 3:
            laplace = (
                gray[1:-1, :-2]
                + gray[1:-1, 2:]
                + gray[:-2, 1:-1]
                + gray[2:, 1:-1]
                - 4 * gray[1:-1, 1:-1]
            )
            if float(laplace.var()) < 3:
                issues.append("Image appears severely blurred")
        return ImageQualityResult(checked=True, usable=not issues, is_plant=None, issues=issues)
