import os


def configure_runtime():
    for name in ("USE_MS_GRAPHRAG", "USE_LIGHTRAG", "USE_NANO_GRAPHRAG"):
        os.environ.setdefault(name, "false")
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    os.environ["CHROMA_PRODUCT_TELEMETRY_IMPL"] = (
        "learning_ext.telemetry.DisabledProductTelemetry"
    )
    os.environ["CHROMA_TELEMETRY_IMPL"] = (
        "learning_ext.telemetry.DisabledProductTelemetry"
    )
