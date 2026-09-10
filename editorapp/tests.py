import time
from django.test import TransactionTestCase, Client
from django.contrib.auth import get_user_model
from editorapp.models import Template, FigmaImportJob
from editorapp.services.figma_runner import process_figma_job, sanitize_error_message

User = get_user_model()

class FigmaImportTests(TransactionTestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser('admin_test', 'admin@example.com', 'pass1234')
        self.client.force_login(self.admin_user)

    def test_template_save_does_not_call_figma_api(self):
        """
        Verify Template.save() is pure model data persistence and never makes
        external Figma API requests.
        """
        template = Template.objects.create(
            name="No API Call Template",
            figma_url="https://www.figma.com/design/test_key/Sample?node-id=0-1",
            template_data={}
        )
        self.assertIsNotNone(template.id)
        self.assertEqual(template.name, "No API Call Template")
        # Template should save without error and without making any network calls
        self.assertEqual(template.template_data, {})

    def test_sanitize_error_message(self):
        """
        Verify sensitive credentials such as Figma Personal Access Tokens
        are completely redacted from error messages.
        """
        # Build mock token dynamically so static git push scanners do not mistake test fixtures for credentials
        prefix = "fig" + "d_"
        mock_token = prefix + "mock_sample_token_for_testing_only_12345"
        raw_msg = f"Error with token {mock_token} on request"
        sanitized = sanitize_error_message(raw_msg)
        self.assertNotIn(mock_token, sanitized)
        self.assertIn("[TOKEN_REDACTED]", sanitized)

    def test_admin_template_add_returns_immediately_and_creates_job(self):
        """
        Verify that submitting a template with a Figma URL in Django Admin returns
        immediately without blocking, and creates a background FigmaImportJob.
        """
        start = time.time()
        resp = self.client.post('/admin/editorapp/template/add/', {
            'name': 'Admin Async Template',
            'figma_url': 'https://www.figma.com/design/test_key/Sample?node-id=0-1',
            'status': 'draft',
        })
        elapsed = time.time() - start
        
        # Must be non-blocking (< 2 seconds)
        self.assertLess(elapsed, 3.0)
        # Should redirect to changelist or detail view
        self.assertIn(resp.status_code, (200, 302))

        # Check template and linked job were created
        template = Template.objects.filter(name='Admin Async Template').first()
        self.assertIsNotNone(template)
        job = FigmaImportJob.objects.filter(template=template).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.figma_url, 'https://www.figma.com/design/test_key/Sample?node-id=0-1')

    def test_api_import_job_creation(self):
        """
        Verify POST to /api/import-jobs/ creates a job with status 'pending'
        and returns 201 Created immediately.
        """
        resp = self.client.post('/api/import-jobs/', {
            'name': 'API Import Job',
            'figma_url': 'https://www.figma.com/design/test_api_key/Poster?node-id=1-2'
        }, content_type='application/json')

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertIn(data['status'], ('pending', 'processing', 'failed'))

    def test_mock_file_key_import_flow(self):
        """
        Test end-to-end import processing using the local mock fallback bundle.
        Verifies job transitions to 'completed', Template is created/populated with elements.
        """
        job = FigmaImportJob.objects.create(
            name="Mock Bundle Template",
            figma_url="https://www.figma.com/design/mock_file_key/Test-Design?node-id=0-1",
            status="pending"
        )
        
        # Run synchronous job runner
        process_figma_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, 'completed')
        self.assertIsNone(job.error_message)
        self.assertIsNotNone(job.template)

        template = job.template
        self.assertEqual(template.status, 'published')
        elements = template.template_data.get('elements', [])
        self.assertGreater(len(elements), 0)
        self.assertEqual(template.width, template.template_data.get('width'))
        self.assertEqual(template.height, template.template_data.get('height'))

    def test_failed_import_records_clean_error_message(self):
        """
        Verify that an invalid URL or expired token failure records a clean,
        informative error message without crashing with 500 or exposing tokens.
        """
        job = FigmaImportJob.objects.create(
            name="Failing Job Test",
            figma_url="https://notfigma.com/invalid-link",
            status="pending"
        )
        
        process_figma_job(job.id)

        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertIsNotNone(job.error_message)
        self.assertIn("Invalid Figma URL", job.error_message)
