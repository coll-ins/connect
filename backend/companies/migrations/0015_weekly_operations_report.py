from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0014_trip_schedule_generation_summary'),
    ]

    operations = [
        migrations.CreateModel(
            name='WeeklyOperationsReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('report_type', models.CharField(choices=[('weekly', 'Weekly operations'), ('manual_renewal', 'Manual renewal reminder')], max_length=20)),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('renewal_date', models.DateField(blank=True, null=True)),
                ('summary', models.JSONField(default=dict)),
                ('email_status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('skipped', 'Skipped'), ('failed', 'Failed')], default='pending', max_length=10)),
                ('email_error', models.CharField(blank=True, max_length=160)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('email_sent_at', models.DateTimeField(blank=True, null=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='weekly_operations_reports', to='companies.company')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='weeklyoperationsreport',
            constraint=models.UniqueConstraint(fields=('company', 'report_type', 'period_start'), name='uniq_company_operations_report_period'),
        ),
        migrations.AddIndex(
            model_name='weeklyoperationsreport',
            index=models.Index(fields=['company', '-created_at'], name='companies_w_company_44d931_idx'),
        ),
    ]
