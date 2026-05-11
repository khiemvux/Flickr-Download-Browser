import unittest
from pathlib import Path

from flickr_downloader_app import (
    album_folder_name,
    collection_info_from_metadata,
    description_path_for,
    filename_from_item,
    is_probably_flickr_url,
    parse_gallery_dl_dump,
    render_about_text,
    sanitize_filename,
    unique_folder,
    QueueJob,
    STATUS_PENDING,
)


class AppCoreTests(unittest.TestCase):
    def test_flickr_url_validation_accepts_public_flickr_urls(self):
        self.assertTrue(is_probably_flickr_url("https://www.flickr.com/photos/example/123"))
        self.assertTrue(is_probably_flickr_url("https://flickr.com/photos/example/albums/456"))

    def test_flickr_url_validation_rejects_non_flickr_urls(self):
        self.assertFalse(is_probably_flickr_url("https://example.com/photos/example/123"))
        self.assertFalse(is_probably_flickr_url("not a url"))

    def test_sanitize_filename_removes_unsafe_characters(self):
        self.assertEqual(sanitize_filename(' Bad/File:Name?.jpg '), "Bad_File_Name_.jpg")
        self.assertEqual(sanitize_filename(""), "flickr_photo")

    def test_filename_from_item_uses_title_id_and_url_extension(self):
        filename = filename_from_item(
            {
                "id": 2341623661,
                "title": "ZB8T0193",
                "url": "https://live.staticflickr.com/example/photo_5k.jpg",
            }
        )
        self.assertEqual(filename, "ZB8T0193_2341623661.jpg")

    def test_description_path_pairs_with_image_base_name(self):
        self.assertEqual(description_path_for(Path("/tmp/photo.jpeg")), Path("/tmp/photo.txt"))

    def test_parse_gallery_dl_dump_extracts_download_items(self):
        payload = """
        [
          [2, {
            "id": 123,
            "title": "Sample",
            "description": "A description",
            "url": "https://live.staticflickr.com/1/sample_o.png"
          }]
        ]
        """
        parsed = parse_gallery_dl_dump(payload, "https://www.flickr.com/photos/example/123")
        self.assertEqual(len(parsed.items), 1)
        self.assertEqual(parsed.items[0].media_url, "https://live.staticflickr.com/1/sample_o.png")
        self.assertEqual(parsed.items[0].filename, "Sample_123.png")
        self.assertEqual(parsed.items[0].description, "A description")

    def test_album_folder_name_uses_title_and_id(self):
        folder = album_folder_name({"title": "Saigon markets", "id": "72157638035079914"})
        self.assertEqual(folder, "Saigon markets - 72157638035079914")

    def test_collection_info_and_about_text_from_album_metadata(self):
        info = collection_info_from_metadata(
            "https://www.flickr.com/photos/97930879@N02/albums/72157638035079914/",
            [
                {
                    "album": {"title": "Saigon markets", "id": "72157638035079914"},
                    "user": {"username": "TommyJapan1", "path_alias": "97930879@N02"},
                }
            ],
        )
        self.assertEqual(info.folder_name, "Saigon markets - 72157638035079914")
        self.assertEqual(
            render_about_text(info),
            "Saigon markets\n"
            "URL: https://www.flickr.com/photos/97930879@N02/albums/72157638035079914/\n"
            "by TommyJapan1: https://www.flickr.com/photos/97930879@N02/\n",
        )

    def test_unique_folder_adds_suffix_when_folder_exists(self):
        base = Path("/tmp/flickr-downloader-test-existing")
        expected = base.with_name(base.name + " (2)")
        if expected.exists():
            expected.rmdir()
        base.mkdir(exist_ok=True)
        try:
            self.assertEqual(unique_folder(base), expected)
        finally:
            base.rmdir()

    def test_queue_job_defaults_to_pending(self):
        job = QueueJob(id=1, url="https://www.flickr.com/photos/example/123", destination=Path("/tmp/out"))
        self.assertEqual(job.status, STATUS_PENDING)
        self.assertEqual(job.completed, 0)
        self.assertEqual(job.failed, 0)


if __name__ == "__main__":
    unittest.main()
