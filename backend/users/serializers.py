import re

from rest_framework import serializers

from .models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(
        required=False, allow_blank=True, write_only=True, max_length=150
    )

    class Meta:
        model = CustomUser
        fields = [
            'id',
            'username',
            'email',
            'phone_number',
            'location',
            'role',
            'company',
            'password',
            'name',
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'min_length': 6},
            'email': {'required': False, 'allow_blank': True},
            'role': {'read_only': True},
            'company': {'read_only': True},
        }

    def create(self, validated_data):
        phone = validated_data['phone_number']
        raw_username = validated_data.pop('username', '').strip()
        username = raw_username or phone.replace('+', 'user_')
        username = re.sub(r'[^A-Za-z0-9@.+_-]+', '_', username).strip('_') or 'user'

        base_username = username
        suffix = 1
        while CustomUser.objects.filter(username=username).exists():
            suffix += 1
            username = f'{base_username}_{suffix}'

        full_name = ' '.join(validated_data.pop('name', '').split())
        first_name, _, last_name = full_name.partition(' ')

        return CustomUser.objects.create_user(
            username=username,
            email=validated_data.get('email', ''),
            phone_number=phone,
            location=validated_data.get('location', ''),
            password=validated_data['password'],
            first_name=first_name,
            last_name=last_name,
        )


class CompanyStaffSerializer(serializers.ModelSerializer):
    """
    Serializer for company-managed staff.

    Company and sensitive Django permission fields are controlled
    by the server and are never accepted from the client.
    """

    company_name = serializers.CharField(
        source='company.name',
        read_only=True
    )

    class Meta:
        model = CustomUser
        fields = [
            'id',
            'username',
            'email',
            'phone_number',
            'location',
            'role',
            'company',
            'company_name',
            'is_active',
        ]
        read_only_fields = [
            'id',
            'company',
            'company_name',
        ]

    def validate_role(self, value):
        allowed_roles = {
            'company_manager',
            'company_auditor',
            'company_operator',
        }

        if value not in allowed_roles:
            raise serializers.ValidationError(
                'Staff role must be company_manager, '
                'company_auditor, or company_operator.'
            )

        return value
