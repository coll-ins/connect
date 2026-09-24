import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { apiRequest } from '../../api';

export default function PaymentReturn(){
  const { bookingId } = useParams();
  const [params] = useSearchParams();
  const [status,setStatus]=useState('checking'),[message,setMessage]=useState('Confirming your payment with Paystack…');
  useEffect(()=>{
    let active=true;
    (async()=>{
      try{
        const data=await apiRequest(`/bookings/payments/${bookingId}/verify/`,{method:'POST',body:{reference:params.get('reference')}});
        if(!active)return;
        if(data.payment_status==='confirmed'){setStatus('success');setMessage('Payment confirmed. Your CONNECT booking is ready.');}
        else {setStatus('pending');setMessage(data.message||'Payment is still being confirmed. Check your bookings in a moment.');}
      }catch(e){if(active){setStatus('error');setMessage(e.message)}}
    })();
    return()=>{active=false};
  },[bookingId,params]);
  return <div className="auth-page"><div className="auth-card payment-status"><div style={{fontSize:52}}>{status==='success'?'✓':status==='error'?'!':'⌛'}</div><p className="eyebrow">CONNECT PAYMENT</p><h1>{status==='success'?'Payment confirmed':status==='error'?'Payment check failed':'Checking payment'}</h1><p className="muted">{message}</p><Link className="btn btn-primary" to="/passenger">Back to passenger dashboard</Link></div></div>;
}
