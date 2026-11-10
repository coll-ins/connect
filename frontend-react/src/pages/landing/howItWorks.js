import { Armchair, Bus, Package } from 'lucide-react';

// What each service asks of the rider, in the order the app asks it.
// Kept in step with SeatMap, DeliveryWizard and CharterWizard.
export const SERVICES = [
  {
    id: 'seat',
    icon: Armchair,
    name: 'Book a seat',
    line: 'Your seat on the next matatu, held before you leave the house.',
    steps: [
      { title: 'Pick route and stage', text: 'Choose the company, your route and the stage you board at.' },
      { title: 'Choose your seat', text: 'Tap a free seat on the bus map, or let us pick one for you.' },
      { title: 'Pay', text: 'M-Pesa or card. The seat is yours the moment it is paid.' },
      { title: 'Track and board', text: 'Watch the bus on the live map, then show your PIN to the driver.' },
    ],
  },
  {
    id: 'parcel',
    icon: Package,
    name: 'Send a parcel',
    line: 'A matatu on your route carries it. The receiver collects it with a PIN.',
    steps: [
      { title: 'From and to', text: 'Pick where the parcel starts and where it is going.' },
      { title: 'Choose the bus', text: 'A company that runs that route carries it on a scheduled trip.' },
      { title: 'Describe and pay', text: 'Say what it is, add the receiver’s name and phone, and pay in the app.' },
      { title: 'Collect with a PIN', text: 'Follow it on the map. The driver hands it over only against the receiver’s PIN.' },
    ],
  },
  {
    id: 'hire',
    icon: Bus,
    name: 'Hire a whole bus',
    line: 'For a wedding, a church trip or a school outing.',
    steps: [
      { title: 'Tell us the trip', text: 'Pick a company, where from and to, the date and how many people.' },
      { title: 'Get a price', text: 'The company replies with a quote, usually within a day.' },
      { title: 'Accept and pay', text: 'Nothing is charged until you accept. Paying confirms the hire.' },
      { title: 'Ride together', text: 'The bus and driver are yours for the trip. Plans change? Cancel in the app.' },
    ],
  },
];
