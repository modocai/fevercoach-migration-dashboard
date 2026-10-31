import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from dashboard_data import project_wix
from build_dashboard import render_wix
import json
class ExportProgressTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=json.loads((Path(__file__).resolve().parents[1]/'data/snapshot.json').read_text(encoding='utf-8'))
    def test_classification_and_private_fields(self):
        raw=copy.deepcopy(self.snapshot['wix']['data'])
        raw['private_path']='must-not-publish'
        public=project_wix(raw)
        self.assertNotIn('private_path',public)
        self.assertEqual(public['legacy_reference_entries'],public['unique_referenced_images']+public['downloaded_font_assets']+public['invalid_reference_count'])
        raw['legacy_reference_entries']+=1
        with self.assertRaises(ValueError):project_wix(raw)
    def test_blog_backup_does_not_claim_full_migration(self):
        self.assertFalse(self.snapshot['wix']['data']['authoritative_wix_export_complete'])
        html=render_wix(self.snapshot['wix'])
        self.assertIn('3,679',html)
        self.assertIn('6,761',html)
        self.assertIn('예약 129',html)
        self.assertIn('GCS',html)
if __name__=='__main__':unittest.main()


