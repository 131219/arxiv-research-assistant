from pathlib import Path
import tarfile


def extract_archive(
    archive_path: Path,
    destination_directory: Path,
) -> Path:
    """
    Extract one TAR archive into the destination directory.
    """
    destination_directory.mkdir(parents=True, exist_ok=True)

    print(f"Extracting {archive_path}")
    print(f"Destination: {destination_directory}")

    with tarfile.open(archive_path, mode="r") as archive:
        archive.extractall(path=destination_directory)

    print("Extraction completed.")
    return destination_directory
