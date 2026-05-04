from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def scope_existing_policies(apps, schema_editor):
    Institution = apps.get_model("institutions", "Institution")
    SavingsPolicy = apps.get_model("savings", "SavingsPolicy")

    template = (
        SavingsPolicy.objects.order_by("-is_active", "-updated_at", "-created_at", "name").first()
    )
    institutions = Institution.objects.order_by("created_at", "name")

    for institution in institutions:
        SavingsPolicy.objects.create(
            institution=institution,
            name=f"{institution.code.upper()} default savings policy",
            minimum_balance=(
                template.minimum_balance if template is not None else Decimal("0.00")
            ),
            withdrawal_charge=(
                template.withdrawal_charge if template is not None else Decimal("0.00")
            ),
            is_active=True,
        )

    SavingsPolicy.objects.filter(institution__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("institutions", "0002_institution_logo_institution_physical_address_and_more"),
        ("savings", "0006_alter_savingstransaction_type_savingspolicy"),
    ]

    operations = [
        migrations.AddField(
            model_name="savingspolicy",
            name="institution",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="savings_policies",
                to="institutions.institution",
            ),
        ),
        migrations.RunPython(scope_existing_policies, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="savingspolicy",
            name="institution",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="savings_policies",
                to="institutions.institution",
            ),
        ),
        migrations.AddIndex(
            model_name="savingspolicy",
            index=models.Index(
                fields=["institution", "is_active"],
                name="sav_policy_inst_active_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="savingspolicy",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("institution",),
                name="savings_policy_one_active_per_institution",
            ),
        ),
    ]
