import re

from rest_framework import serializers
from .models import CustomUser


class UserSerializer(serializers.ModelSerializer):
    username = serializers.CharField()

    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'phone_number', 'location', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        username = validated_data.pop('username').strip()
        username = re.sub(r'[^A-Za-z0-9@.+_-]+', '_', username).strip('_') or 'user'
        base_username = username
        suffix = 1
        while CustomUser.objects.filter(username=username).exists():
            suffix += 1
            username = f'{base_username}_{suffix}'

        user = CustomUser.objects.create_user(
            username=username,
            phone_number=validated_data['phone_number'],
            location=validated_data['location'],
            password=validated_data['password']
        )
        return user