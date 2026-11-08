// The legal documents shown at /legal/<slug>. Every rule about money here is
// what the code does; change them together (see the file named next to each).
import { BUSINESS } from './business';

const contact = () => {
  const ways = [BUSINESS.email, BUSINESS.phone].filter(Boolean);
  return ways.length
    ? `Contact us at ${ways.join(' or ')}, or through Help in the app.`
    : 'Contact us through Help in the app.';
};

const terms = {
  slug: 'terms',
  title: 'Terms of Service',
  summary: 'The rules for using CONNECT, the technology platform that connects you with transport companies to book seats, send parcels and hire buses.',
  sections: [
    {
      h: 'Who we are and what CONNECT does',
      body: [
        `CONNECT is a technology platform operated by ${BUSINESS.entity}, ${BUSINESS.address} ("CONNECT", "we", "us"). It lets you find and book seats on matatus and buses, send parcels on scheduled trips, and request to hire a whole bus from independent transport companies.`,
        'CONNECT is an intermediary. We are not a transport company, courier or bus hire operator. We do not own, operate or control any vehicle, driver, crew, route, timetable or fare, and we have no authority over how a transport company runs its business.',
        'When you book a seat, send a parcel or hire a bus, your contract for that service is with the transport company (sacco or operator) shown in the app. That company is the carrier. It alone decides and is responsible for its fares, timetables, vehicles, drivers and crew, the safety of passengers and goods, parcel handling, hire quotes, and the licences and insurance its business needs.',
        'CONNECT is responsible only for the platform itself: the app and its systems, your account, collecting payments on behalf of the transport company, applying the automatic refund rules built into the platform, and protecting the personal data we hold.',
      ],
    },
    {
      h: 'Your account',
      body: [
        {
          list: [
            'You must be at least 18 years old to create an account. A person under 18 may travel on a booking made by a parent or guardian, who is responsible for that booking.',
            'Give your real name and a phone number you control. We use the phone number to identify you and contact you about your trips.',
            'Keep your password private. You are responsible for bookings made from your account until you tell us it has been misused.',
            'We may suspend or close an account used for fraud, abuse of staff or other passengers, repeated no-shows, or attempts to break or misuse the service. We will tell you why unless the law or an investigation prevents it.',
          ],
        },
      ],
    },
    {
      h: 'Booking a seat',
      body: [
        'A booking is a request for seats on a specific trip. It is confirmed when payment is confirmed, or, for cash, when the conductor or driver records your cash payment.',
        {
          list: [
            'Online payment (M-PESA, card or bank through Paystack) must be completed within 20 minutes. An unpaid online booking is cancelled after that and its seats are released.',
            'If you choose cash, your seat is held until the trip departs. Pay the conductor or driver when you board. A cash booking that has not been paid when the trip departs is cancelled.',
            'You can hold up to 3 unpaid bookings at a time.',
            'Fares are set by the transport company, not by CONNECT, and shown in Kenya Shillings before you pay. The fare you see when you book is the fare charged through the app.',
            'Show your booking or boarding code when you board. Boarding is controlled by the transport company’s crew, who may refuse a passenger who cannot show a valid booking, is a danger to others, or breaks the law or the company’s rules.',
          ],
        },
        'Departure times are set by the transport company and can change because of traffic, weather, breakdowns or police checks. Live locations and arrival estimates come from the company’s vehicles and are a guide, not a promise.',
      ],
    },
    {
      h: 'Cancellations, no-shows and refunds',
      body: [
        'The platform applies the refund rules in the Refund and Cancellation Policy automatically, on behalf of the transport company. In short: you get a full refund when the transport company cancels or cannot carry you; you get half the fare back if you cancel before boarding starts or do not board. Anything outside those rules, such as compensation for a delay or a cash refund, is for the transport company to decide.',
      ],
    },
    {
      h: 'Parcels and bus hire',
      body: [
        'Sending a parcel is also governed by the Parcel Terms. Hiring a bus is also governed by the Bus Hire Terms. If those terms and these Terms disagree on a parcel or a hire, the specific terms apply.',
      ],
    },
    {
      h: 'Payments',
      body: [
        'CONNECT collects online payments as the transport company’s payment agent and pays the company its share after the trip. Payments are processed by Paystack, a licensed payment processor. Your card, bank or M-PESA details are entered with Paystack; CONNECT never sees or stores your full card number or PIN.',
        'Cash is paid directly to the transport company’s crew. CONNECT never receives cash.',
        'Payments are taken in Kenya Shillings. Your bank or mobile money provider may charge its own fees, which we do not control.',
        'If you are charged more than once for the same booking, or charged for a booking that was not confirmed, we refund the extra charge automatically to the account you paid from.',
        'The Wallet screen in the app shows your trip spending. It does not hold money and cannot be topped up.',
      ],
    },
    {
      h: 'How you must use CONNECT',
      body: [
        {
          list: [
            'Do not make bookings you do not intend to use to block seats from other passengers.',
            'Do not use CONNECT for anything illegal, or to send prohibited items.',
            'Do not try to access other people’s accounts or data, interfere with the app, or copy it at scale.',
            'Treat drivers, crew and other passengers with respect.',
          ],
        },
      ],
    },
    {
      h: 'Who is responsible for what',
      body: [
        'The transport company is solely responsible for the transport service: carrying you safely, its vehicles, drivers and crew, the goods in its care, its fares and timetables, and complying with Kenyan law, including the Traffic Act and the rules of the National Transport and Safety Authority (NTSA). Claims about injury, loss or damage during a trip, a lost or damaged parcel, or how a hire was carried out are claims against the transport company.',
        'CONNECT is responsible for running the platform with reasonable care and skill: recording your booking correctly, charging the amount shown, passing your booking to the transport company, applying the platform’s refund rules, and protecting your personal data.',
        'To the extent the law allows, CONNECT is not liable for anything done or not done by a transport company, its drivers or crew, or for delays, cancellations, route changes or events on the road, and our total liability to you for any booking, parcel or hire is limited to the amount you paid through the app for it.',
        'Nothing in these Terms limits any right you have under the Consumer Protection Act, 2012 or other Kenyan law that cannot be limited by agreement, or excludes liability for death or personal injury caused by negligence, or for fraud.',
      ],
    },
    {
      h: 'Complaints',
      body: [
        `For problems with the app, your account, a payment or your data: ${contact()} Include your booking, parcel or hire reference. We aim to reply within 2 working days.`,
        'Complaints about the transport service itself (a driver, vehicle, crew, delay, parcel or hire) are for the transport company to resolve. We pass them to the company with your booking details and tell you its response. Safety issues can also be reported to the NTSA.',
      ],
    },
    {
      h: 'Changes to these Terms',
      body: [
        'We may update these Terms when the service or the law changes. We will show the new version in the app before it applies to you. Bookings already confirmed keep the terms that applied when you made them.',
      ],
    },
    {
      h: 'Law and disputes',
      body: [
        'These Terms are governed by the laws of Kenya. If a dispute cannot be resolved through our complaints process, it may be taken to the courts of Kenya, or to the Small Claims Court where the amount allows.',
      ],
    },
  ],
};

const refunds = {
  slug: 'refunds',
  title: 'Refund and Cancellation Policy',
  summary: 'The refund rules the CONNECT platform applies automatically on behalf of transport companies: when you get money back, how much, and how long it takes.',
  sections: [
    {
      h: 'Seat bookings',
      body: [
        {
          table: [
            ['What happens', 'Refund'],
            ['You cancel an unpaid booking', 'Nothing was charged'],
            ['An unpaid online booking expires after 20 minutes', 'Nothing was charged'],
            ['You cancel a paid booking before boarding starts', 'Half the fare'],
            ['You do not board within 15 minutes of departure (no-show)', 'Half the fare'],
            ['The transport company cancels the trip', 'Full fare'],
            ['The company cancels your booking because it cannot carry you', 'Full fare'],
            ['An incident (breakdown, accident) stops the trip', 'Your choice: full refund or a seat on a later trip'],
          ],
        },
        'Once boarding has started you can no longer cancel a booking in the app.',
        'If you paid cash, CONNECT never received the money. Any refund is for the transport company to decide and pay; ask the crew or the company.',
        'Refunds of less than KES 5 cannot be sent through our payment processor and are not paid.',
      ],
    },
    {
      h: 'Online payments that go wrong',
      body: [
        {
          list: [
            'If you close the payment page or the payment fails, nothing is charged and you can try again or choose another way to pay.',
            'If you are charged twice for the same booking, or pay on an old payment page after starting a new payment or switching to cash, the extra charge is refunded in full automatically.',
            'If the amount charged does not match the booking, the booking is not confirmed and the charge is refunded in full.',
          ],
        },
      ],
    },
    {
      h: 'Parcels',
      body: [
        {
          table: [
            ['What happens', 'Refund'],
            ['You cancel before the parcel is picked up', 'Full delivery fee'],
            ['The trip carrying the parcel is cancelled', 'Full delivery fee'],
            ['The parcel was never picked up and the trip has ended', 'Full delivery fee'],
            ['The parcel was picked up but not delivered', 'For the transport company to resolve; see the Parcel Terms'],
          ],
        },
      ],
    },
    {
      h: 'Bus hire',
      body: [
        {
          table: [
            ['What happens', 'Refund'],
            ['You cancel before paying the quote', 'Nothing was charged'],
            ['You cancel a paid hire 48 hours or more before departure', 'Full hire price'],
            ['You want to cancel a paid hire less than 48 hours before departure', 'At the transport company’s discretion; contact the company'],
            ['The transport company cancels a paid hire', 'Full hire price'],
          ],
        },
      ],
    },
    {
      h: 'How and when refunds are paid',
      body: [
        'Refunds go back to the account you paid from: the same M-PESA number, card or bank account. We cannot send a refund to a different account.',
        'We send refunds as soon as the rule above applies, usually within minutes. Your bank or M-PESA usually shows the money within 5 to 10 working days. If you have not received it after 10 working days, contact us with your reference and we will trace it.',
      ],
    },
  ],
};

const parcels = {
  slug: 'parcels',
  title: 'Parcel Terms',
  summary: 'Extra terms for sending a parcel on a scheduled trip.',
  sections: [
    {
      h: 'How parcel delivery works',
      body: [
        'You book a parcel on a specific scheduled trip, from one stage to a later stage on the same route, and pay the delivery fee set by the transport company for that size. The driver collects the parcel from you at the pickup stage and hands it to the receiver at the drop-off stage.',
        'The receiver gets the parcel by giving the driver the handover PIN shown in your app. Share the PIN only with the receiver. Anyone who gives the correct PIN is treated as the receiver. After 5 wrong PIN attempts the parcel is locked and you must contact us.',
      ],
    },
    {
      h: 'What you must not send',
      body: [
        {
          list: [
            'Weapons, ammunition and explosives.',
            'Drugs, narcotics and any substance that is illegal to possess.',
            'Flammable, toxic, corrosive or otherwise dangerous goods, including gas cylinders and fuel.',
            'Live animals.',
            'Cash, bank cards, cheques and other money.',
            'Anything stolen, counterfeit or that is illegal to send.',
            'Anything that is leaking, smells strongly, or is packed so badly it could hurt someone or damage other goods.',
          ],
        },
        'Do not send jewellery, important documents you cannot replace, or anything you cannot afford to lose. CONNECT does not offer insurance on parcels.',
        'The driver may refuse a parcel that looks unsafe, is bigger than the size you paid for, or that they reasonably believe breaks these rules. A refused parcel is treated as not picked up. The police may inspect parcels, and we will cooperate with lawful requests.',
      ],
    },
    {
      h: 'The receiver’s details',
      body: [
        'You must have the receiver’s permission to give us their name and phone number. We share them only with the transport company and driver handling the delivery.',
      ],
    },
    {
      h: 'If something goes wrong',
      body: [
        'The parcel service is provided by the transport company, which is the carrier and is solely responsible for the parcel from pickup to hand-over. CONNECT never handles parcels.',
        'If a parcel is picked up but not delivered within 48 hours of the trip ending, the platform flags it and we pass it to the transport company to resolve. The driver can still complete the delivery with the PIN.',
        'Report a lost or damaged parcel within 7 days with your tracking code. We pass the report and the parcel record to the transport company; any claim for loss or damage is against that company. To the extent the law allows, CONNECT’s own liability for a parcel is limited to the delivery fee you paid through the app.',
        'Refunds for parcels are in the Refund and Cancellation Policy.',
      ],
    },
  ],
};

const hire = {
  slug: 'bus-hire',
  title: 'Bus Hire Terms',
  summary: 'Extra terms for hiring a whole bus from a transport company.',
  sections: [
    {
      h: 'How bus hire works',
      body: [
        'You send a request to a transport company with your trip details: purpose, pickup, destination, dates and number of passengers. Departure must be at least 24 hours away and a hire can last up to 14 days.',
        'The company decides whether to accept the request and sets the price, the driver and the bus. A quote is valid until the time shown. Paying the quote in full confirms the hire.',
        'The hire contract is between you and the transport company. CONNECT only passes the request and quote between you, collects the payment on the company’s behalf, and applies the cancellation rules below. The company is solely responsible for carrying out the hire.',
      ],
    },
    {
      h: 'Your responsibilities',
      body: [
        {
          list: [
            'Give accurate trip details. The number of passengers must not exceed the seats in the bus; the driver will refuse to carry more passengers than the bus is licensed for.',
            'Be at the pickup point at the agreed time. Waiting time, extra stops, route changes and extra days are agreed with the company and may cost more.',
            'You are responsible for the behaviour of your group and for damage your group causes to the bus beyond normal wear.',
            'Alcohol, illegal substances and prohibited items are not allowed on board unless the company agrees in writing and the law allows it.',
          ],
        },
      ],
    },
    {
      h: 'Cancellations',
      body: [
        'You can cancel a request at any time before you pay. You can cancel a paid hire in the app 48 hours or more before departure for a full refund. Less than 48 hours before departure, contact the transport company; any refund is at its discretion.',
        'If the company cancels a paid hire, for example because the bus breaks down, you get a full refund.',
      ],
    },
    {
      h: 'Safety and the law',
      body: [
        'The transport company must hold the licences and insurance needed to hire out the bus and carry your group, and the driver must follow the Traffic Act and NTSA rules, including speed limits and driving hours. The driver may stop or end the trip if continuing would be unsafe or illegal.',
      ],
    },
  ],
};

const privacy = {
  slug: 'privacy',
  title: 'Privacy Policy',
  summary: 'What personal data CONNECT collects, why, who sees it, and your rights under the Data Protection Act, 2019.',
  sections: [
    {
      h: 'Who is responsible for your data',
      body: [
        `${BUSINESS.entity}, ${BUSINESS.address}, is the data controller for the personal data held in the CONNECT platform, and this is the part of the service CONNECT is directly responsible for. Each transport company receives only the data it needs to run your trip, parcel or hire, and is a separate data controller responsible for how it uses that data. ${contact()}`,
      ],
    },
    {
      h: 'What we collect',
      body: [
        {
          table: [
            ['Data', 'When', 'Why'],
            ['Name, phone number, password (stored only as a secure hash), usual location', 'When you sign up', 'To create your account and identify you to the crew'],
            ['Bookings, parcels, hires, boarding records, no-show count', 'When you use the service', 'To provide the service, prevent seat hoarding and keep records the law requires'],
            ['Payment references, amounts and status', 'When you pay', 'To confirm payments and send refunds. Card and M-PESA details stay with Paystack'],
            ['Receiver name and phone number', 'When you send a parcel', 'So the driver can deliver it'],
            ['Your live location', 'Only while you choose to share it for a booking', 'So your driver can find you at the pickup point'],
            ['Driver live location', 'While a driver is on a trip', 'To show passengers where the vehicle is'],
            ['Device and log data (IP address, browser, times of requests)', 'Whenever you use the app', 'Security, preventing fraud and fixing faults'],
          ],
        },
        'We do not collect national ID numbers, and we do not use advertising or tracking cookies. The app stores your sign-in session in your browser so you stay signed in.',
      ],
    },
    {
      h: 'Our legal basis',
      body: [
        'We process your data to perform our contract with you (your bookings), to meet legal obligations (such as tax and transport records), for our legitimate interests in keeping the service safe and preventing fraud, and with your consent for location sharing, which you can stop at any time.',
      ],
    },
    {
      h: 'Who we share it with',
      body: [
        {
          list: [
            'The transport company, driver and crew for your trip, parcel or hire: your name, phone number, pickup and booking details.',
            'Paystack, to process payments and refunds.',
            'Africa’s Talking, to send SMS messages.',
            'Our hosting providers, which store the data on our behalf under contract.',
            'Police, courts or regulators, when the law requires it.',
          ],
        },
        'We do not sell your personal data.',
      ],
    },
    {
      h: 'Data stored outside Kenya',
      body: [
        'Some of our service providers store data on servers outside Kenya, such as in the European Union or the United States. Where this happens, we use providers that protect personal data to a standard comparable to Kenyan law, as the Data Protection Act, 2019 requires.',
      ],
    },
    {
      h: 'How long we keep it',
      body: [
        'We keep your account data while your account is open. We keep booking and payment records for 7 years after the transaction, to meet Kenyan tax and financial record-keeping laws. For location, we store only the most recent position you shared, on that booking, and the driver’s most recent position; we do not keep a location history. When data is no longer needed it is deleted or made anonymous.',
      ],
    },
    {
      h: 'Your rights',
      body: [
        'Under the Data Protection Act, 2019 you have the right to be told how your data is used, to see a copy of it, to have wrong data corrected, to have data deleted where we no longer need it, to object to processing, and to ask for your data in a portable format.',
        `${contact()} We reply within 30 days. Records we must keep by law (such as payment records) cannot be deleted before the legal period ends, but we will stop using them for anything else.`,
        'If you are not satisfied, you can complain to the Office of the Data Protection Commissioner (ODPC), www.odpc.go.ke.',
      ],
    },
    {
      h: 'Security',
      body: [
        'We use encrypted connections, store passwords only as secure hashes, limit staff access to the data each role needs, and keep transport companies’ data separate from each other. If a data breach puts you at risk, we will tell you and the ODPC as the law requires.',
      ],
    },
    {
      h: 'Children',
      body: [
        'CONNECT accounts are for adults. We do not knowingly collect data from children under 18 except as passengers on a booking made by a parent or guardian.',
      ],
    },
    {
      h: 'Changes',
      body: [
        'We will show any important change to this policy in the app before it applies.',
      ],
    },
  ],
};

export const DOCUMENTS = [terms, privacy, refunds, parcels, hire];
export const documentBySlug = (slug) => DOCUMENTS.find((d) => d.slug === slug);
