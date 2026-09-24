import re

from rest_framework import serializers

from .models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(required=False, allow_blank=True)

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

        return CustomUser.objects.create_user(
            username=username,
            email=validated_data.get('email', ''),
            phone_number=phone,
            location=validated_data.get('location', ''),
            password=validated_data['password'],
        )
