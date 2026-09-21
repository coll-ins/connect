

# Create your views here.
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Wallet
from .serializers import WalletSerializer


@api_view(['GET'])
def get_my_wallet(request):
    if not request.user.is_authenticated:
        return Response(
            {'error': 'Login required'},
            status=status.HTTP_401_UNAUTHORIZED
        )

    wallet, _ = Wallet.objects.get_or_create(user=request.user)

    return Response(WalletSerializer(wallet).data)
